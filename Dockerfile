FROM python:3.10

RUN useradd -m merdetti

USER merdetti

COPY . /app

WORKDIR /app

RUN pip install -r requirements.txt

CMD python /app/merdetti.py
