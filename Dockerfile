FROM python:3.12-alpine

WORKDIR /app

COPY ilo_fan_alert.py .

CMD ["python", "-u", "ilo_fan_alert.py"]
