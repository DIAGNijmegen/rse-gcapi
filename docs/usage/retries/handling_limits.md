# Retrying in the face of limits

Grand Challenge has several limits in place to ensure fair use and system reliability.

One such limit you could run into is the maximum number of uploads. Uploads are temporarily stored before being processed in the background and automatically cleaned up afterward.

If you hit the limit during a function call (e.g. `add_case_to_archive`) the uploads will remain unassigned.

The uploads will eventually be cleaned up automatically, but can temporarily block creating any new uploads until that happens.

If you retry the function call before enough uploads have been cleaned up, you might unintentionally be blocking yourself by creating yet more unassigned uploads.

The upload limit being reached is generally reported by a 400-coded response from Grand Challenge which will tell you:

> "You have created too many uploads. Please try again later."

One solution could be to use a retry strategy to catch these responses, wait for a while, and continue from where your program initially ran into these limits.

Whether this strategy fits your specific use case is up to you.

The following example strategy would retry after 5 minutes: a similar construct would work for other limit-related responses.

!!! Example
    ```Python
    --8<-- "docs/examples/upload_retry_strategy.py"
    ```

    You can use it by passing it to the Client when initializing it:

    ```Python
    token = 'my-personal-api-token'
    client = gcapi.Client(
        token=token,
        retry_strategy=UploadRetryStrategy,
    )
    ```
