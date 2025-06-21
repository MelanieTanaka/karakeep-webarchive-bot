# Use a lightweight official Python image as the base
FROM python:3.11-slim-bookworm

# Set the working directory inside the container
WORKDIR /app

# Copy only the requirements file first
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Command to run bot script
ENTRYPOINT ["python"]
CMD ["archivebot.py"]