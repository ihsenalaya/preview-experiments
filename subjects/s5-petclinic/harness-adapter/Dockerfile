FROM springcommunity/spring-petclinic-rest:3.4.0 AS petclinic-app

FROM python:3.12-slim

# JRE required to run the Spring Boot JAR
RUN apt-get update && apt-get install -y --no-install-recommends default-jre-headless \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy the Spring Boot fat-JAR
COPY --from=petclinic-app /app/*.jar /app/spring-petclinic-rest.jar 2>/dev/null || \
    COPY --from=petclinic-app /spring-petclinic-rest*.jar /app/spring-petclinic-rest.jar

# Python test dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Test scripts (contract: /app/tests/)
COPY tests/ /app/tests/
COPY wrapper.py /wrapper.py

EXPOSE 9966
CMD ["python3", "/wrapper.py"]
