FROM python:3.11-slim

RUN useradd -ms /bin/bash myuser
RUN groupadd -r mygroup
RUN usermod -a -G mygroup myuser

WORKDIR /home/myuser

USER myuser

ADD copy_io.py .

ENTRYPOINT ["python", "copy_io.py"]
