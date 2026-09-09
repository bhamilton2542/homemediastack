FROM python:3.12-slim
WORKDIR /app
RUN pip install flask --no-cache-dir
COPY app.py index.html ./
EXPOSE 5700
CMD ["python", "app.py"]
