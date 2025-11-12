import httpx

import gcapi


class UploadRetryStrategy(gcapi.retries.SelectiveBackoffStrategy):
    """Retry strategy that handles upload limits specifically.

    In addition to the standard retriable errors handled by
    SelectiveBackoffStrategy, this strategy also retries on
    BAD_REQUEST responses that indicate the user has created too many
    uploads.
    """

    def __init__(self):
        super().__init__(
            backoff_factor=0.1,
            maximum_number_of_retries=5,  # Applies to other retriable errors
        )

    def get_delay(self, latest_response):
        delay = None  # Do not retry at all, by default

        if latest_response.status_code == httpx.codes.BAD_REQUEST:
            response_json = latest_response.json()
            non_field_errors = response_json.get("non_field_errors", [])
            if (
                len(non_field_errors) == 1
                and "you have created too many uploads"
                in non_field_errors[0].casefold()
            ):
                print("Retrying upload due to too many uploads.")
                delay = 300  # Delay for 5 minutes

        return delay
