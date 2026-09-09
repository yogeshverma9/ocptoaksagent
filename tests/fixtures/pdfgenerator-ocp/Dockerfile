FROM docker-public.artifacts.internal.spark.co.nz/ubi9/nodejs-20-minimal:latest
USER root:root

RUN npm config set proxy http://cicdnexus/repository/npm-proxy/ && \
    npm config set https-proxy http://cicdnexus/repository/npm-proxy/ && \
    npm config set registry http://cicdnexus/repository/npm-registry/ && \
    npm config set strict-ssl false && \
    mkdir -p /home/app && \
    chmod -R 777 /home/app

WORKDIR /home/app

COPY ./package*.json /home/app/

RUN npm ci

COPY . /home/app

RUN chmod 777 /home/app/src/images

RUN node -v &&\ 
    npm -v &&\
    npm run build
