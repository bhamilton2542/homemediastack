FROM python:3.12-slim
WORKDIR /app
RUN pip install flask --no-cache-dir
COPY app.py index.html ./
EXPOSE 5500
CMD ["python", "app.py"]
