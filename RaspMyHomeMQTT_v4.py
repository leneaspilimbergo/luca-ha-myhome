# /usr/bin/python
# =================================================================
# RaspMyHome - Monitoraggio impianto BTICINO MyHome da Raspberry Pi
# 
# (c) 2013 by Luca ENEA-SPILIMBERGO
#             luca.enea.spilimbergo@gmail.com
#             www.viadellaluna2.it
# =================================================================
# Resta in ascolto sul bus MyHome, tramite un gateway BTicino L4686SDK
# e salva nel database i dati relativi a accensione/spegnimento luci,
# temperature dei locali
# =================================================================
# 
# Storia delle revisioni
# -----------------------------------------------------------------
# 0.1    01.11.13    Prima bozza: ascolto bus e creazione file log
# 0.2    02.11.13    Salva nel database lo stato delle luci e delle temperature. 
#                    Chiede stato luci all'avvio
# 0.3    03.11.13    Inserito delay 50ms per scaricare CPU
# 0.4    16.11.13    Inserita gestione pipe comandi (da interfaccia web) - 
#                    NON VA, SERVONO THREAD SEPARATI
# 0.5    25.11.13    Inserita analisi comandi di gruppo
# 0.6    16.12.13    Ricezione comandi seriali ed elaborazione comandi da web su thread separati
# 0.7    06.03.15	 Salva storico temperature nel DB
# 0.8    14.01.16    Nuova struttura database
# 3.1    17.01.20	 Pubblica su MQTT - solo stato luci e temperatura (cambio nome al file, ora si chiama MQTT_v1)
# 3.2    18.01.20    Accetta anche comandi da MQTT  
# 3.3    23.01.20    Gestisce anche comandi frangisole  
# 4.0    11.03.20    Gestisce la posizione dei frangisole
import datetime
import time
import os
import sys    
import serial
import string
import threading
import Queue
import paho.mqtt.client as mqtt	# MQTT library

CONFIG_MQTT_BROKER	    = "192.168.0.11" 
CONFIG_MQTT_CLIENTID    = "RaspMyHomeClient"
CONFIG_MQTT_TOPIC	    = "RaspMyHome"
CONFIG_SERIAL_PORT      = "/dev/ttyUSB1"
CONFIG_VERSION          = "3.3"
# frangisole
CONFIG_COVER_MIN_ID     = 61
CONFIG_COVER_MAX_ID     = 78
CONFIG_COVER_TMAX       = 60

# classe per ricezione dati da seriale
class MySerialThread(threading.Thread):
    def __init__(self, name, serial, queue):
        threading.Thread.__init__(self)
        self.name = name
        self.queue = queue
        self.serial = ser
    def run(self):
        try:
            global dtAdesso
            sys.stderr.write(self.name + ": Avvio...\n")
            while 1:
                msg = ""
                previous =""
                end = 0
                # ciclo lettura singolo messaggio (termina con ##)
                while (end == 0):
                    c = ser.read(1)
                    msg += c
                    if (c=="#" and previous=="#"):
                        end = 1
                    else:
                        previous = c
                end = 0
                # legge orario attuale
                dtAdesso = datetime.datetime.now()
                # salva nel log
                # sys.stderr.write(msg + "\n")
                # correzione messaggio (lo fa iniziare dal primo *) e toglie il ## finale
                msg.lstrip()                        # toglie spazi iniziale
                pos = msg.find('*')                 # cerca * iniziale
                msg = msg[(pos+1):]                 # prende dopo *
                msg = msg[0:len(msg)-2]             # non considera ## finale
                # mette il messaggio in coda
                self.queue.put(msg)
                # salva nel log
                sys.stderr.write(self.name + ": " + msg + "\n")
        except Exception, e:
            sys.stderr.write("%s: Eccezione=%s\n" % self.name, e.message )

# inizializza strutture dati per frangisole
def CoverInit():
    global CoverLastCmd
    global CoverLastTimestamp
    global CoverLastPosition
    global CoverCount 
    # quante cover totali?
    CoverLastCmd = [0]
    CoverLastPosition = [0]
    CoverLastTimestamp =[datetime.datetime.now()]
    CoverCount = CONFIG_COVER_MAX_ID - CONFIG_COVER_MIN_ID
    # inizializza
    for i in range(0,CoverCount):
        CoverLastCmd.append(0)
        CoverLastPosition.append(0.0)
        CoverLastTimestamp.append(datetime.datetime.now())
    
# MQTT : callback
def MQTT_onconnect(client, userdata, flags, rc):
    global MQTT_connected 
    MQTT_connected = True
    sys.stderr.write("MQTT connected!\n")
    # si abbona ai comandi da HA
    client.subscribe("RaspMyHome/cmd/#")  # comandi luci e frangisole
    sys.stderr.write("MQTT subscribed!\n")

def MQTT_ondisconnect(client, userdata, rc):
    global MQTT_connected
    MQTT_connected = False
    sys.stderr.write("MQTT disconnected!\n")

def MQTT_onmessage(mosq, obj, msg):
    global MQTT_cmd_queue
    # LUCI
    # formato comando nella coda: *1*[stato]*[who] - esempio *1*0*52 
    # topic:    RaspMyHome/cmd/light/[who]
    # payload:  ON/OFF 
    # FRANGISOLE
    # formato comando nella coda: *2*[direzione]*[who] - esempio *1*0*52 
    # topic:    RaspMyHome/cmd/cover/[who]
    # payload:  closed/opened/closing/opening 
    # command:  STOP/OPEN/CLOSE
    try:
        sys.stderr.write("MQTT:" + msg.topic + "\n")
        topic_elements = msg.topic.split("/")
        # che messaggio
        if (topic_elements[2]=="light"):
            # comando luci
            if (msg.payload == "ON"):
                value=1
            else:
                value=0
            myhomecmd = "*1*%s*%s##" % (str(value), topic_elements[3])
        elif (topic_elements[2]=="cover"):
            # comando frangisole
            if (msg.payload == "STOP"):
                    value = "0"
            if (msg.payload == "OPEN"):
                    value = "1"
            if (msg.payload == "CLOSE"):
                    value = "2"
            myhomecmd = "*2*%s*%s##" % (str(value), topic_elements[3])
        sys.stderr.write("MQTT MESSAGES: " + msg.topic + " " + str(msg.qos) + " " + str(msg.payload) + "\n")
        sys.stderr.write("MQTT MyHome cmd: WHO=" + topic_elements[3] + " STATUS=" + str(value) + "(" + myhomecmd + ")\n")
        MQTT_cmd_queue.put(myhomecmd) 
    except Exception, e:
        sys.stderr.write("MQTT_onmessage: Eccezione=%s\n" % e.message )
   
# ==========================================================
# PROGRAMMA PRINCIPALE
# ==========================================================
# variabili globali
global MQTT_connected
global MQTT_cmd_queue
global CoverLastCmd
global CoverLastTimestamp
global CoverCount 

try:
    sys.stderr.write("Avvio...\n")

    CoverInit()

    tNow = datetime.datetime.now()
    tLastCheck = tNow
    state=""
    position=0

    # porta seriale
    ser = serial.Serial(CONFIG_SERIAL_PORT,115200, timeout=None)
    sys.stderr.write("Aperta porta " + CONFIG_SERIAL_PORT + "\n")

    # coda per comunicazione main-thread comandi
    MQTT_cmd_queue = Queue.Queue()
    # coda per comunicazione main-thread seriale
    qSerialCmds = Queue.Queue()

    # MQTT
    MQTT_connected = False
    mqtt_client = mqtt.Client(CONFIG_MQTT_CLIENTID)
    mqtt_client.on_connect = MQTT_onconnect
    mqtt_client.on_message = MQTT_onmessage
    mqtt_client.username_pw_set("mqttuser", "mtRoute66")
    # si connette al broker MQTT
    mqtt_client.connect(CONFIG_MQTT_BROKER, keepalive=1800)
    mqtt_client.loop_start() 
    # si abbona ai comandi da HA
    mqtt_client.subscribe("RaspMyHome/luci_cmd/#")
    # dizionario stato luci, frangisole
    light_status_text = ["OFF","ON"]
    cover_status_text = ["unknown", "opening", "closing"]

    # avvia thread per ricezione dati da seriale
    threadSerial = MySerialThread("SerialThread", ser, qSerialCmds)
    threadSerial.start()

    # parte chiedendo lo stato attuale delle luci
    ser.write("*#1*0##");
except Exception, e:
    sys.stderr.write("MAIN-INIT: Eccezione=%s\n" % e.message )

# ciclo continuo
while 1:
    i=0
    try:
        # MESSAGGI DA BUS MYHOME
        if (qSerialCmds.qsize() > 0):
            # recupera messaggio
            msg = qSerialCmds.get()
            sys.stderr.write("MAIN: Ricevuto msg MyHome '{}'\n".format(msg))
            # analisi messaggio
            fields = msg.split('*')
            # che messaggio ?
            msgtype = fields[0]
            # LUCI ------------------------------------------
            if (msgtype =="1"):
                light_id = int(fields[2])
                light_status = int(fields[1])
                # e' un comando di gruppo? (2-3 piano primo, 4-5 piano terra)
                if ((light_id == 3) or (light_id == 5)):
                    # richiede lo stato complessivo di tutte le luci
                    ser.write("*#1*0##");
                    # TODO: da rivedere: basterebbe rileggere solo il piano relativo al comando
                else:
                    # MQTT: prepara i dati
                    topic = "RaspMyHome/light/%s" % light_id
                    payload = light_status_text[light_status]
                    # MQTT connessione
                    if (MQTT_connected == False):
                        # si connette al broker MQTT
                        mqtt_client.connect(CONFIG_MQTT_BROKER, keepalive=1800)
                        mqtt_client.loop_start() 
                    # MQTT pubblica stato luce
                    mqtt_client.publish(topic,payload,2,True)    #qos=1, retain=True
            # FRANGISOLE-------------------------------------
            # 2*1*36 alza frangisole 36
            # 2*0*36 ferma frangisole 36
            # 2*2*36 abbassa frangisole 36
            elif (msgtype =="2"):
                cover_id = int(fields[2])
                cover_cmd = int(fields[1])
                # simulazione posizione
                iIndex = cover_id - CONFIG_COVER_MIN_ID
                # era un comando di STOP?
                if (cover_cmd==0):
                    # da quanto tempo?
                    tNow=datetime.datetime.now()
                    tElapsed = tNow - CoverLastTimestamp[i]
                    if (tElapsed.total_seconds()>CONFIG_COVER_TMAX):
                        # era in apertura?
                        if (CoverLastCmd[iIndex]==1):
                            state = "open"
                            position = 100
                        # era in chiusura?
                        if (CoverLastCmd[iIndex]==2):
                            state = "closed"
                            position = 0
                else:
                    state = cover_status_text[cover_cmd]

                # MQTT pubblica stato frangisole
                topic = "RaspMyHome/cover/%s/state" % cover_id
                sys.stderr.write("MQTT: %s:%s \n" % (topic, state) )
                # MQTT connessione
                if (MQTT_connected == False):
                    # si connette al broker MQTT
                    mqtt_client.connect(CONFIG_MQTT_BROKER, keepalive=1800)
                    mqtt_client.loop_start() 
                mqtt_client.publish(topic,state,2,True)    #qos=1, retain=True
                # MQTT pubblica posizione frangisole
                topic = "RaspMyHome/cover/%s/position" % cover_id
                sys.stderr.write("MQTT: %s:%s \n" % (topic, state) )
                # MQTT connessione
                if (MQTT_connected == False):
                    # si connette al broker MQTT
                    mqtt_client.connect(CONFIG_MQTT_BROKER, keepalive=1800)
                    mqtt_client.loop_start() 
                mqtt_client.publish(topic,position,2,True)    #qos=1, retain=True
                
                # salva ultimo comando e tempo
                CoverLastCmd[iIndex]=cover_cmd
                CoverLastTimestamp[iIndex]=datetime.datetime.now()
                #sys.stderr.write("ARRAY SET: index=%s,%s,%s \n" % (iIndex, CoverLastCmd[iIndex], CoverLastTimestamp[iIndex]) )
            # TERMOREGOLAZIONE-------------------------------
            elif ((msgtype == "4") or (msgtype == "#4")):
                where = fields[1]
                what = fields[2]
                if ((what=="0") and (where!="")):
                    where = int(fields[1])
                    if (len(fields)>3):
                        temperature = float(fields[3])/10
                    else:
                        temperature = 0.0
                    sys.stderr.write("Temperatura: zona {}: T={:01} \n".format(where, temperature))
                    # MQTT: prepara i dati                  
                    topic = "RaspMyHome/temperature/%s" % where
                    payload = "%4.2f" % temperature
                    # MQTT connessione
                    if (MQTT_connected == False):
                        # si connette al broker MQTT
                        mqtt_client.connect(CONFIG_MQTT_BROKER, keepalive=1800)
                        mqtt_client.loop_start() 
                    # MQTT pubblica stato temperatura
                    mqtt_client.publish(topic,payload,1,True)    #qos=1, retain=True

            # ANTIFURTO -------------------------------------
            elif (msgtype == "5"):
                sys.stderr.write("Messaggio Antifurto\n")
        
        # COMANDI DA MQTT
        if (MQTT_cmd_queue.qsize() > 0):
            cmd = MQTT_cmd_queue.get().encode("ascii")
            # log
            sys.stderr.write("MAIN: Ricevuto comando da MQTT '{}'\n".format(cmd))
            # invia il comando # sintassi = *1*0*31##
            ser.write(cmd);
            sys.stderr.write("MAIN: Inviato comando {}\n".format(cmd))
        
        # SIMULAZIONE POSIZIONE FRANGISOLE
        # controllo ogni secondo
        tNow = datetime.datetime.now()
        if (tNow.second != tLastCheck.second):
            tLastCheck = tNow
            for i in range(0, CoverCount):
                if (CoverLastCmd[i]!=0):
                    tElapsed = tNow - CoverLastTimestamp[i]
                    # quale frangisole?
                    cover_id = iIndex + CONFIG_COVER_MIN_ID
                    #sys.stderr.write("COVER-ID:=%s, LastCmd=%s\n" % (i, CoverLastCmd[i]))
                    #sys.stderr.write("LASTCHANGE: %s\n" % CoverLastTimestamp[i])
                    #sys.stderr.write("NOW=%s\n" % tNow)
                    #sys.stderr.write("SECONDS=%i\n" % tElapsed.total_seconds())
                    delta = float(100)/float(CONFIG_COVER_TMAX)
                    sys.stderr.write("DELTA=%f\n" % delta)
                    # simula posizione
                    if (CoverLastCmd[i]==1): # apre (100 = tutto aperto)
                        CoverLastPosition[i] += delta
                        if (CoverLastPosition[i]>100): CoverLastPosition[i]=100                        
                    if (CoverLastCmd[i]==2): # chiude (0 = tutto chiuso)
                        CoverLastPosition[i] -= delta
                        if (CoverLastPosition[i]<0): CoverLastPosition[i]=0
                    # scrive 
                    topic = "RaspMyHome/cover/%s/position" % cover_id
                    #sys.stderr.write("MQTT: %s:%s \n" % (topic, payload) )
                    # MQTT connessione
                    if (MQTT_connected == False):
                        # si connette al broker MQTT
                        mqtt_client.connect(CONFIG_MQTT_BROKER, keepalive=1800)
                        mqtt_client.loop_start() 
                    # MQTT pubblica posizione
                    mqtt_client.publish(topic,int(CoverLastPosition[i]),2,True)    #qos=1, retain=True
        # FINE CICLO 
        # ============================================================
        # delay
        time.sleep(0.05)
    # fine ciclo
    except Exception, e:
        sys.stderr.write("MAIN-LOOP: Eccezione = %s\n" % e.message )
# fine programma
ser.close();
