FROM python:3.12-slim
WORKDIR /app
RUN pip install flask apscheduler --no-cache-dir
COPY app.py index.html ./
EXPOSE 5600
CMD ["python", "app.py"]
