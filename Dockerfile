# Use bullseye over bookworm for better image size and ffmpeg compatibility
FROM python:3.12-slim-bullseye

# Install required packages
RUN apt-get update --allow-releaseinfo-change && \
    apt-get install -y --no-install-recommends ffmpeg wireless-tools && \
    apt-get clean && \
    pip install poetry && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy minimum required files into the image
COPY . /app/

# Only install main dependencies for better docker caching
RUN poetry install

# Copy the rest of the files and install the remaining deps in a separate layer
COPY pikaraoke ./pikaraoke

EXPOSE 5555
