from io import BytesIO

import SimpleITK as sitk
from PIL import Image as PILImage

from django.http import Http404
from rest_framework import serializers


class PILImageSerializer(serializers.BaseSerializer):
    """
    Read-only serializer that returns a PIL image from a Image instance.
    If "width" and "height" are passed as extra serializer content, the
    PIL image will be resized to those dimensions.
    If the image is 3D it will return the center slice of the image.
    """

    def to_representation(self, instance):
        try:
            image_itk = instance.get_sitk_image()
        except:
            raise Http404
        pil_image = self.convert_itk_to_pil(image_itk)
        try:
            pil_image.thumbnail(
                (self.context["width"], self.context["height"]),
                PILImage.ANTIALIAS,
            )
        except KeyError:
            pass
        return pil_image

    @staticmethod
    def convert_itk_to_pil(image_itk):
        depth = image_itk.GetDepth()
        image_nparray = sitk.GetArrayFromImage(image_itk)
        if depth > 0:
            # Get center slice of image if 3D
            image_nparray = image_nparray[depth // 2]
        return PILImage.fromarray(image_nparray)


class BytesImageSerializer(PILImageSerializer):
    """
    Read-only serializer that returns a BytesIO image from an Image instance.
    Subclasses PILImageSerializer, so the image may be resized and only the central
    slice of a 3d image will be returned
    """

    def to_representation(self, instance):
        image_pil = super().to_representation(instance)
        return self.create_thumbnail_as_bytes_io(image_pil)

    @staticmethod
    def create_thumbnail_as_bytes_io(image_pil):
        buffer = BytesIO()
        image_pil.save(buffer, format="png")
        return buffer.getvalue()
