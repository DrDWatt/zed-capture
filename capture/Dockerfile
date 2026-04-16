# ZED Capture Container for Jetson
# Based on L4T with ZED SDK
FROM nvcr.io/nvidia/l4t-base:r32.7.1

ENV DEBIAN_FRONTEND=noninteractive
ENV LOGNAME=root
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    libusb-1.0-0-dev \
    libhidapi-libusb0 \
    libopencv-dev \
    python3 \
    python3-pip \
    python3-dev \
    python3-numpy \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav \
    gstreamer1.0-tools \
    wget \
    curl \
    zstd \
    && rm -rf /var/lib/apt/lists/*

# Install ZED SDK for Jetson (L4T 32.7)
RUN wget -q -O ZED_SDK_Tegra.run \
    https://download.stereolabs.com/zedsdk/4.0/l4t32.7/jetsons && \
    chmod +x ZED_SDK_Tegra.run && \
    ./ZED_SDK_Tegra.run -- silent skip_cuda && \
    rm ZED_SDK_Tegra.run && \
    rm -rf /var/lib/apt/lists/*

# Install Python packages and ZED Python API
RUN python3 -m pip install --upgrade pip && \
    python3 -m pip install cython requests && \
    python3 /usr/local/zed/get_python_api.py || true

# Copy capture scripts
COPY capture_service.py /app/capture_service.py
COPY start_capture.sh /app/start_capture.sh
COPY stop_capture.sh /app/stop_capture.sh
RUN chmod +x /app/*.sh

WORKDIR /app

# Create video output directory
RUN mkdir -p /mnt/videos

CMD ["python3", "/app/capture_service.py"]
