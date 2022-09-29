FROM python:2-slim
#
# ---------- SOURCES -------------------
ADD RaspMyHomeMQTT_v4.py /
#
# ---------- DEPENDENCIES --------------
RUN pip install paho-mqtt
RUN pip install pyserial
#
# ---------- RUN COMMANDS --------------
CMD ["python", "./RaspMyHomeMQTT_v4.py"]
#
# ---------- INFO ----------------------
LABEL "Name"="RaspMyHomeMQTT"
LABEL "Version"="4.0"
LABEL "VersionDate"="11.04.2020"
LABEL "Description"="Python programs to gather data from BTICINO MyHome"
LABEL "Developer"="Luca ENEA-SPILIMBERGO"
LABEL "Email"="luca.enea.spilimbergo@gmail.com"
