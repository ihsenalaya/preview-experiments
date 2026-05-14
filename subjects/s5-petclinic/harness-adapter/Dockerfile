FROM springcommunity/spring-petclinic-rest:3.4.0

USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip \
    && pip3 install requests --break-system-packages \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY tests/ /app/tests/
COPY wrapper.py /wrapper.py

EXPOSE 9966
CMD ["python3", "/wrapper.py"]
