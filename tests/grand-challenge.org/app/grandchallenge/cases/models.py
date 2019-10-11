import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List

import SimpleITK as sitk
from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models
from guardian.shortcuts import assign_perm

from grandchallenge.challenges.models import ImagingModality
from grandchallenge.core.models import UUIDModel
from grandchallenge.core.storage import protected_s3_storage
from grandchallenge.studies.models import Study
from grandchallenge.subdomains.utils import reverse

logger = logging.getLogger(__name__)


class UPLOAD_SESSION_STATE:
    created = "created"
    queued = "queued"
    running = "running"
    stopped = "stopped"


class RawImageUploadSession(UUIDModel):
    """
    A session keeps track of uploaded files and forms the basis of a processing
    task that tries to make sense of the uploaded files to form normalized
    images that can be fed to processing tasks.
    """

    max_length_error_message = 256

    creator = models.ForeignKey(
        to=settings.AUTH_USER_MODEL,
        null=True,
        default=None,
        on_delete=models.SET_NULL,
    )

    session_state = models.CharField(
        max_length=16, default=UPLOAD_SESSION_STATE.created
    )

    processing_task = models.UUIDField(null=True, default=None)

    error_message = models.CharField(
        max_length=max_length_error_message,
        blank=False,
        null=True,
        default=None,
    )

    imageset = models.ForeignKey(
        to="datasets.ImageSet",
        null=True,
        default=None,
        on_delete=models.CASCADE,
    )

    annotationset = models.ForeignKey(
        to="datasets.AnnotationSet",
        null=True,
        default=None,
        on_delete=models.CASCADE,
    )

    algorithm_image = models.ForeignKey(
        to="algorithms.AlgorithmImage",
        null=True,
        default=None,
        on_delete=models.CASCADE,
    )

    algorithm_result = models.OneToOneField(
        to="algorithms.Result",
        null=True,
        default=None,
        on_delete=models.CASCADE,
    )

    reader_study = models.ForeignKey(
        to="reader_studies.ReaderStudy",
        null=True,
        default=None,
        on_delete=models.SET_NULL,
    )

    def __str__(self):
        return (
            f"Upload Session <{str(self.pk).split('-')[0]}>, "
            f"({self.session_state})"
        )

    def save(self, *args, skip_processing=False, **kwargs):
        created = self._state.adding

        super().save(*args, **kwargs)

        if created and not skip_processing:
            self.process_images()

    def process_images(self):
        # Local import to avoid circular dependency
        from grandchallenge.cases.tasks import build_images

        try:
            RawImageUploadSession.objects.filter(pk=self.pk).update(
                session_state=UPLOAD_SESSION_STATE.queued,
                processing_task=self.pk,
            )

            build_images.apply_async(args=(self.pk,))

        except Exception as e:
            RawImageUploadSession.objects.filter(pk=self.pk).update(
                session_state=UPLOAD_SESSION_STATE.stopped,
                error_message=f"Could not start job: {e}",
            )
            raise e

    def get_absolute_url(self):
        return reverse(
            "cases:raw-files-session-detail", kwargs={"pk": self.pk}
        )

    @property
    def api_url(self):
        return reverse("api:upload-session-detail", kwargs={"pk": self.pk})


class RawImageFile(UUIDModel):
    """
    A raw image file is a file that has been uploaded by a user but was not
    preprocessed to create a standardized image representation.
    """

    upload_session = models.ForeignKey(
        RawImageUploadSession, blank=False, on_delete=models.CASCADE
    )

    # Copy in case staged_file_id is set to None
    filename = models.CharField(max_length=128, blank=False)

    staged_file_id = models.UUIDField(blank=True, null=True)

    error = models.CharField(
        max_length=256, blank=False, null=True, default=None
    )


def image_file_path(instance, filename):
    return (
        f"{settings.IMAGE_FILES_SUBDIRECTORY}/{instance.image.pk}/{filename}"
    )


def case_file_path(instance, filename):
    # legacy method, but used in a migration so cannot delete.
    return image_file_path(instance, filename)


class Image(UUIDModel):
    COLOR_SPACE_GRAY = "GRAY"
    COLOR_SPACE_RGB = "RGB"
    COLOR_SPACE_RGBA = "RGBA"
    COLOR_SPACE_YCBCR = "YCBCR"

    COLOR_SPACES = (
        (COLOR_SPACE_GRAY, "GRAY"),
        (COLOR_SPACE_RGB, "RGB"),
        (COLOR_SPACE_RGBA, "RGBA"),
        (COLOR_SPACE_YCBCR, "YCBCR"),
    )

    COLOR_SPACE_COMPONENTS = {
        COLOR_SPACE_GRAY: 1,
        COLOR_SPACE_RGB: 3,
        COLOR_SPACE_RGBA: 4,
        COLOR_SPACE_YCBCR: 4,
    }

    EYE_OD = "OD"
    EYE_OS = "OS"
    EYE_UNKNOWN = "U"
    EYE_NA = "NA"
    EYE_CHOICES = (
        (EYE_OD, "Oculus Dexter (right eye)"),
        (EYE_OS, "Oculus Sinister (left eye)"),
        (EYE_UNKNOWN, "Unknown"),
        (EYE_NA, "Not applicable"),
    )

    STEREOSCOPIC_LEFT = "L"
    STEREOSCOPIC_RIGHT = "R"
    STEREOSCOPIC_UNKNOWN = "U"
    STEREOSCOPIC_EMPTY = None
    STEREOSCOPIC_CHOICES = (
        (STEREOSCOPIC_LEFT, "Left"),
        (STEREOSCOPIC_RIGHT, "Right"),
        (STEREOSCOPIC_UNKNOWN, "Unknown"),
        (STEREOSCOPIC_EMPTY, "Not applicable"),
    )

    FOV_1M = "F1M"
    FOV_2 = "F2"
    FOV_3M = "F3M"
    FOV_4 = "F4"
    FOV_5 = "F5"
    FOV_6 = "F6"
    FOV_7 = "F7"
    FOV_UNKNOWN = "U"
    FOV_EMPTY = None
    FOV_CHOICES = (
        (FOV_1M, FOV_1M),
        (FOV_2, FOV_2),
        (FOV_3M, FOV_3M),
        (FOV_4, FOV_4),
        (FOV_5, FOV_5),
        (FOV_6, FOV_6),
        (FOV_7, FOV_7),
        (FOV_UNKNOWN, "Unknown"),
        (FOV_EMPTY, "Not applicable"),
    )

    name = models.CharField(max_length=128)
    study = models.ForeignKey(Study, on_delete=models.CASCADE, null=True)
    origin = models.ForeignKey(
        to=RawImageUploadSession, null=True, on_delete=models.SET_NULL
    )
    modality = models.ForeignKey(
        ImagingModality, on_delete=models.SET_NULL, null=True
    )

    width = models.IntegerField(blank=False)
    height = models.IntegerField(blank=False)
    depth = models.IntegerField(null=True)
    resolution_levels = models.IntegerField(null=True)
    color_space = models.CharField(
        max_length=5, blank=False, choices=COLOR_SPACES
    )

    eye_choice = models.CharField(
        max_length=2,
        choices=EYE_CHOICES,
        default=EYE_NA,
        help_text="Is this (retina) image from the right or left eye?",
    )
    stereoscopic_choice = models.CharField(
        max_length=1,
        choices=STEREOSCOPIC_CHOICES,
        default=STEREOSCOPIC_EMPTY,
        null=True,
        help_text="Is this the left or right image of a stereoscopic pair?",
    )
    field_of_view = models.CharField(
        max_length=3,
        choices=FOV_CHOICES,
        default=FOV_EMPTY,
        null=True,
        help_text="What is the field of view of this image?",
    )

    def __str__(self):
        return f"Image {self.name} {self.shape_without_color}"

    @property
    def shape_without_color(self) -> List[int]:
        result = []
        if self.depth is not None:
            result.append(self.depth)
        result.append(self.height)
        result.append(self.width)
        return result

    @property
    def shape(self) -> List[int]:
        result = self.shape_without_color
        color_components = self.COLOR_SPACE_COMPONENTS[self.color_space]
        if color_components > 1:
            result.append(color_components)
        return result

    def get_sitk_image(self):
        """
        This function returns the image that belongs to this model as an SimpleITK image. It requires that exactly one
        MHD/RAW file pair is associated with the model. Otherwise it wil raise a MultipleObjectsReturned or
        ObjectDoesNotExist exception.
        :return: SimpleITK image
        """
        # self.files should contain 1 .mhd file
        mhd_file = self.files.get(file__endswith=".mhd")
        raw_file = self.files.get(file__endswith="raw")

        file_size = 0
        for file in (mhd_file, raw_file):
            if not file.file.storage.exists(name=file.file.name):
                raise FileNotFoundError(f"No file found for {file.file}")

            # Add up file sizes of mhd and raw file to get total file size
            file_size += file.file.size

        # Check file size to guard for out of memory error
        if file_size > settings.MAX_SITK_FILE_SIZE:
            raise IOError(
                f"File exceeds maximum file size. (Size: {file_size}, Max: {settings.MAX_SITK_FILE_SIZE})"
            )

        with TemporaryDirectory() as tempdirname:
            for file in (mhd_file, raw_file):
                infile = file.file.open("rb")
                try:
                    with open(
                        Path(tempdirname) / Path(file.file.name).name, "wb"
                    ) as outfile:
                        buffer = True
                        while buffer:
                            buffer = infile.read(1024)
                            outfile.write(buffer)
                except:
                    infile.close()
                    raise

            try:
                sitk_image = sitk.ReadImage(
                    str(Path(tempdirname) / Path(mhd_file.file.name).name)
                )
            except RuntimeError as e:
                logging.error(
                    f"Failed to load SimpleITK image with error: {e}"
                )
                raise

        return sitk_image

    def permit_viewing_by_retina_users(self):
        """ Calling this function will give the retina graders and retina admins object specific permissions
        to view this image. """
        # Set object level view permissions for retina_graders and retina_admins
        for group_name in (
            settings.RETINA_GRADERS_GROUP_NAME,
            settings.RETINA_ADMINS_GROUP_NAME,
        ):
            group = Group.objects.get(name=group_name)
            assign_perm("view_image", group, self)

    @property
    def api_url(self):
        return reverse("api:image-detail", kwargs={"pk": self.pk})

    class Meta:
        ordering = ("name",)


class ImageFile(UUIDModel):
    IMAGE_TYPE_MHD = "MHD"
    IMAGE_TYPE_TIFF = "TIFF"
    IMAGE_TYPE_DZI = "DZI"

    IMAGE_TYPES = (
        (IMAGE_TYPE_MHD, "MHD"),
        (IMAGE_TYPE_TIFF, "TIFF"),
        (IMAGE_TYPE_DZI, "DZI"),
    )

    image = models.ForeignKey(
        to=Image, null=True, on_delete=models.CASCADE, related_name="files"
    )
    image_type = models.CharField(
        max_length=4, blank=False, choices=IMAGE_TYPES, default=IMAGE_TYPE_MHD
    )
    file = models.FileField(
        upload_to=image_file_path, blank=False, storage=protected_s3_storage
    )


class FolderUpload:
    def __init__(self, image, folder):
        self.image = image
        self.folder = folder

    def destination_filename(self, file_path):
        return (
            f"{settings.IMAGE_FILES_SUBDIRECTORY}/{self.image.pk}/"
            f"{file_path.parent.parent.stem}/{file_path.parent.stem}/{file_path.name}"
        )

    def save(self):
        # Saves all the files in the folder, respecting the parents folder structure
        # 2 directories deep
        for root, _, files in os.walk(self.folder):
            for file in files:
                source_filename = Path(root) / file
                destination_filename = self.destination_filename(
                    source_filename
                )
                with open(source_filename, "rb") as open_file:
                    protected_s3_storage.save(destination_filename, open_file)
