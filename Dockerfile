FROM python:3.9-alpine3.14
MAINTAINER RiotKit <riotkit.org>

ARG JOBBER_VERSION="1.4.4"
ARG JOBBER_BUILD_SUFFIX="-r0"
ARG USER=backup-controller
ARG UID=1000
ARG GID=1000
ENV CONFIG="backup-controller.conf.yaml"
ENV DEBUG="false"

# Create a non-privileged user
RUN addgroup --gid $GID $USER \
    && adduser \
        --disabled-password \
        --gecos "" \
        --home "/home/$USER" \
        --ingroup "$USER" \
        --uid "$UID" \
        "$USER"

WORKDIR /tmp

# Execute everything in bash from now instead of using /bin/sh
RUN apk update && apk add --no-cache bash
SHELL ["/bin/bash", "-c"]

# install docker client, and shell utilities as dependencies required by built-in Backup Maker adapters
# in case, when using "sh" transport to execute backup inside same container
RUN apk add --no-cache libcurl docker git postgresql-client mysql-client tar sudo gnupg curl

# install jobber (a cron-like alternative)
RUN cd / && wget https://github.com/dshearer/jobber/releases/download/v$JOBBER_VERSION/jobber-$JOBBER_VERSION$JOBBER_BUILD_SUFFIX.apk \
    && tar xvf jobber-*.apk \
    && ln -s /usr/libexec/jobber* /usr/bin/ \
    && rm jobber-*.apk

# install as system wide inside container. GIT is required for version information for Python's PBR
ADD ./ /backup-controller
ADD .git /backup-controller/.git
WORKDIR /backup-controller
USER root
RUN set -x; apk add --virtual .build-deps gcc musl-dev python3-dev curl-dev libffi-dev \
    && pip install -r ./requirements.txt \
    && ./setup.py build sdist \
    && ./setup.py install \
    && apk del .build-deps \
    && rm -rf /backup-controller

# Now we will operate only on /home/backup-controller directory
ADD backup-controller.conf.yaml /home/$USER/backup-controller.conf.yaml
ADD docker-files/.jobber /home/$USER/.jobber
RUN mkdir -p /home/$USER/logs /var/jobber/0 && touch /home/$USER/logs/jobber.log
RUN chown root:root -R /home/$USER /var/jobber/0

ADD docker-files/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /home/$USER

# backup-controller is just a scheduler, it should not need root privileges
USER $USER

ENTRYPOINT ["/entrypoint.sh"]
CMD ["--unixsocket", "/home/$USER/cmd.sock", "/home/$USER/.jobber"]
