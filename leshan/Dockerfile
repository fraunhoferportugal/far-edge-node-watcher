FROM python:3.12.0-alpine

ENV PT=Europe/Lisbon
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

LABEL maintainer="João Oliveira <joao.oliveira@fraunhofer.pt>"
LABEL version="1.0"

ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8

RUN pip install SSEClient
RUN pip install kubernetes

ADD main.py /

CMD [ "python3","-u", "main.py", "127.0.0.1", "registry-1.docker.io", "/var/tmp/local-registry" ]