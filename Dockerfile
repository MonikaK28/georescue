FROM python:3.12-slim

WORKDIR /code

# Install system dependencies required by geopandas/osmnx
RUN apt-get update && apt-get install -y \
    build-essential \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file
COPY ./requirements.txt /code/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copy the app code
COPY ./app /code/app
COPY ./locations.json /code/locations.json

# Set environment variable for real road routing
ENV USE_OSMNX=1

# Expose the port Hugging Face expects (7860)
EXPOSE 7860

# Run the FastAPI server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
