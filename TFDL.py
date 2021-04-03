import base64
from datetime import datetime, date, timedelta
import glob
from multiprocessing import Pool
import os
import re
import requests
import subprocess
import time
from time import sleep
import urllib

#bs4
from bs4 import BeautifulSoup
#japanize-kivy
import japanize_kivy
#kivy
from kivy.app import App
from kivy.core.window import Window
Window.size = (500,500)
from kivy.core.text import LabelBase, DEFAULT_FONT
from kivy.uix.widget import Widget

# const
from DownLoadList import *

################################################################################
#                                                                              #
#    If you want to use the 'Area Free', which is limited to the Radiko        #
#    PREMIUM members, set the below two parameters.                            #
#    If you do not have to use it, leave the parameters as default.            #
#                                                                              #
################################################################################

premium_email    = ''
premiun_password = ''

################################################################################

class TimefreeDownloadApp(App):
    def __init__(self, **kwargs):
        super(TimefreeDownloadApp,self).__init__(**kwargs)
        if is_premium: self.title = 'Radio Timefree Download PREMIUM'
        else: self.title = 'Radio Timefree Download'

    def build(self):
        return MainScreen()

################################################################################

def checkRenew():
    mtime = str(os.path.getmtime(cwd+"/DownLoadList.py"))
    renew = 0
    with open(cwd+"/temp/makeKV/timestamp") as r:
        dummy = r.readline()
        renew =  (mtime != dummy)
        r.close()

    if renew:
        with open(cwd+"/temp/makeKV/timestamp", mode='w') as t:
            t.write(mtime)
            t.close()
    return renew

def makeKV():
    file_out = cwd+"/timefreedownload.kv"
    with open(file_out, mode='w') as f:
        with open(cwd+"/temp/makeKV/preamble.txt") as r0:
            f.write(r0.read()+'\n')
            r0.close()

        for name,dict_ in DLL.items():
            with open(cwd+"/temp/makeKV/day_preamble.txt") as r1:
                f.write(r1.read())
                r1.close()
            f.write('                text:"%s"\n' %name)
            f.write('                on_press: root.on_click_%s()\n' %name)
            f.write('            BoxLayout:\n')
            f.write('                orientation: "vertical"\n')

            for dict in dict_:
                for i, id in enumerate(dict):
                    if i%2 == 0:
                        f.write('                BoxLayout:\n')
                    f.write('                    BoxLayout:\n')
                    f.write('                        Switch:\n')
                    f.write('                            id: %s\n' %id)
                    f.write('                        PGLabel:\n')
                    f.write('                            text:"%s"\n' %dict["%s" %id][0])
                    if i == len(dict)-1 and i%2 == 0:
                        f.write('                    BoxLayout:\n')
        with open(cwd+"/temp/makeKV/postscript.txt") as r2:
            f.write(r2.read())
            r2.close()
    print("## KV is revised ##")
    return

################################################################################

# Login to the Radiko Premium members and get the cookies.
def Premium_login(email, password):
    global premium_cookie
    global is_premium
    print('## Radiko Premium Login ##')
    session = requests.session()
    user_data = {'mail':email, 'pass':password}
    res = session.post('https://radiko.jp/ap/member/login/login',data = user_data)
    if res.status_code != 200:
        print('ERROR:%d cannot login to Premium' %res.status_code)
        return

    premium_cookie = session.cookies
    is_premium = True
    print('successfully logged in')
    return

################################################################################

# Radiko.jp authorization: get the AuthToken which enables us to access the data.
url1,url2 = "https://radiko.jp/v2/api/auth1","https://radiko.jp/v2/api/auth2"
def Authorization():
    headers1 = {'X-Radiko-App':'pc_html5', 'X-Radiko-App-Version':'0.0.1', 'X-Radiko-User':'dummy', 'X-Radiko-Device':'pc'}
    response1 = requests.get(url1, headers = headers1)
    AuthToken, l, o = response1.headers['X-Radiko-AuthToken'], int(response1.headers['X-Radiko-KeyLength']), int(response1.headers['X-Radiko-KeyOffset'])
    fullkey_pc = 'bcd151073c03b352e1ef2fd66c32209da9ca0afa'
    PartialKey = base64.b64encode(fullkey_pc.encode('utf-8')[o:o+l])
    headers2 = {'X-Radiko-AuthToken': AuthToken, 'X-Radiko-PartialKey': PartialKey, 'X-Radiko-User':'dummy','X-Radiko-Device':'pc'}
    if is_premium: response2 = requests.get(url2, headers = headers2, cookies = premium_cookie)
    else: response2 = requests.get(url2, headers = headers2)
    print(response2.text)

    return AuthToken

################################################################################

# Look for the target program from the radio schedule.
def LookForProgram(self,StaID,target,WeekDay):
    dummy_day = date.today()
    if self.ids["a_week_ago"].active: dummy_day = dummy_day - timedelta(days=2)
    if WeekDay != 0:
        while True:
            weekday = dummy_day.weekday()
            if weekday != WeekDay - 1: dummy_day = dummy_day - timedelta(days=1)
            else: break
    i = 0
    while True:
        day_fomat = '{0:%Y%m%d}'.format(dummy_day)
        xml = urllib.request.urlopen("http://radiko.jp/v3/program/station/date/"+day_fomat+"/"+StaID+".xml")
        soup = BeautifulSoup(xml, "xml").find(string = target)
        if soup == None and i < 8:
            dummy_day = dummy_day - timedelta(days=1)
            i += 1
        elif i == 8: return 1, 1
        else: break
    prog = soup.find_parent("prog")
    StartTime, EndTime = prog.get("ft"), prog.get("to")
    return StartTime, EndTime
    #"http://radiko.jp/v3/program/station/weekly/"\+StaID+".xml"

################################################################################

################################################################################
#                                                                              #
#    We use 'aria2c' as downloader and 'ffmpeg' to joint the data fragment     #
#    into single output file. They are called with function 'subprocess'.      #
#    The parameter 'threads' representes how many threads are uesd for them.   #
#    Ajusting the parameter to your own environment may affect the             #
#    downloading time.                                                         #
#                                                                              #
#    If you want to change the style of output file name, edit the definition  #
#    of 'title_full' as you like. You can also change the parent directory     #
#    of the output file by modifying the parameter 'output_folder'.            #
#                                                                              #
#    When you want to change the file format of the output file(e.g. mp3),     #
#    edit extension in the definition of 'title_full' and change the options   #
#    for ffmpeg command in 'cmd_ffmpeg'. To change the file fomat, we have     #
#    to encode the audio file: taking external time to complete the task.      #
#    Please reffer the document of ffmpeg for the detail of the options.       #
#                                                                              #
################################################################################

def DLwrapper(self,List):
    #### LookForProgram ####
    StartTime, EndTime = LookForProgram(self,List[0],List[1],List[3])
    if StartTime == 1:
        print("\n"+target)
        print("ERROR: cannot find the program on the schedule")
        return

    # DL by time
    if len(List) == 6:
        StartTime = StartTime[:8] + List[4] + "00"
        EndTime = EndTime[:8] + List[5] + "00"

    DL(self,List[0],List[2],List[3],StartTime,EndTime)
    return

def DL(self,StaID,title,WeekDay,StartTime,EndTime):
    start = time.time()

    day = StartTime[:8]
    time1, time2 = int(StartTime[8]), int(StartTime[9])
    day = datetime.strptime(day,'%Y%m%d')
    if time1 == 0 and time2 < 5:  day = day - timedelta(days=1)
    day = datetime.strftime(day,'%Y_%m_%d')

    title_full = title+day+'.aac'                              #output file name
    path = output_folder+title_full                            #output file path

    #### if the file already exists  ####
    if os.path.exists(path):
        print("\n"+title)
        print("The program has already downloaded.")
    else:
        headers = {'X-Radiko-AuthToken': AT}

        #### get chunk-url-list ####
        url_timefree = "https://radiko.jp/v2/api/ts/playlist.m3u8?station_id="+StaID+"&l=15&ft="+StartTime+"&to="+EndTime
        res_timefree = requests.get(url_timefree, headers = headers)
        m3u8_link = re.search('https://radiko.jp/v2/api/ts/chunklist/[a-zA-Z0-9_/-]{1,61}.m3u8', res_timefree.text)
        if m3u8_link == None:
            print("\n"+title_full)
            print("ERROR: Radiko.jp says '"+res_timefree.text + "'\n")
            return
        chunk_url_list = m3u8_link.group()
        elapsed_time0 = time.time() - start

        #### aria2c ####
        start = time.time()
        print("\n"+title_full)
        print("aria2c...")
        res_chunklist = requests.get(chunk_url_list, headers = headers)
        object_list = re.findall('https://media.radiko.jp/sound/[a-zA-Z0-9_/-]{1,61}.aac',res_chunklist.text)
        args = [(i, object_list, AT) for i in range(4)]
        with Pool(processes=threads) as pool:
            pool.map(aria2c_wrapper, args)
        pool.close()
        print("\n(Download is completed)")
        elapsed_time1 = time.time() - start
        sleep(0.02)

        #### ffmpeg ####
        start = time.time()
        print("\nffmpeg...")
        filelist_in_temp = sorted(glob.glob(cwd+'/temp/*.aac'))
        with open(cwd+'/temp/list_aac.txt','w') as f:
            for i, element in enumerate(filelist_in_temp):
                f.write("file "+filelist_in_temp[i]+('\n'))
        list_aac_txt = cwd+'/temp/list_aac.txt'
        cmd_ffmpeg = "ffmpeg -loglevel quiet -threads "+str(threads)+" -f concat -safe 0 -i "+list_aac_txt+" -acodec copy "+path
        subprocess.call(cmd_ffmpeg, shell = True)
        elapsed_time2 = time.time() - start

        print("\n"+str(os.path.getsize(path)/1000000)+"MB")
        print("set_up:{0}".format(elapsed_time0) + "[sec]")
        print("aria2c:{0}".format(elapsed_time1) + "[sec]")
        print("ffmpeg:{0}".format(elapsed_time2) + "[sec]\n")

        #### delete the chunks in temporary ####
        for file in filelist_in_temp: os.remove(file)

    return

################################################################################

#aria2c wrapper for multiprocessing
def aria2c_wrapper(args):
    return aria2c_multi(*args)

def aria2c_multi(n,object_list,AT):
    cwd = os.getcwd()
    leng = len(object_list)/4
    with open('./temp/list_' +str(n)+'.txt','w') as f:
        i = int(n*leng)
        while i < (n+1)*leng:
            f.write(object_list[i]+ ('\n'))
            i += 1
    cmd_aria2c = "aria2c --console-log-level='error' --download-result='hide' --header='X-Radiko-AuthToken: "+AT+"' -s 16 -j 16 -x 16 -t 5"\
                 " -i "+cwd+"/temp/list_"+str(n)+".txt -d "+cwd+"/temp"
    subprocess.call(cmd_aria2c, shell = True)
    return

################################################################################

class MainScreen(Widget):
    def __init__(self):
        super(MainScreen,self).__init__()

    def on_click_Mon(self):
        bool[1] = not bool[1]
        for id in Mon[0]: self.ids[id].active = bool[1]
        return

    def on_click_Tue(self):
        bool[2] = not bool[2]
        for id in Tue[0]: self.ids[id].active = bool[2]
        return

    def on_click_Wed(self):
        bool[3] = not bool[3]
        for id in Wed[0]: self.ids[id].active = bool[3]
        return

    def on_click_Thu(self):
        bool[4] = not bool[4]
        for id in Thu[0]: self.ids[id].active = bool[4]
        return

    def on_click_Fri(self):
        bool[5]= not bool[5]
        for id in Fri[0]: self.ids[id].active = bool[5]
        return

    def on_click_Sta(self):
        bool[6] = not bool[6]
        for id in Sat[0]: self.ids[id].active = bool[6]
        return

    def on_click_Sun(self):
        bool[0] = not bool[0]
        for id in Sun[0]: self.ids[id].active = bool[0]
        return

    # Actions when DL button is clicked
    def on_click_DL(self):
        for name,dict_ in DLL.items():
            for dict in dict_:
                for id in dict:
                    if self.ids["%s" %id].active: DLwrapper(self,dict["%s" %id][1])


        print("\nAll completed")
        return

################################################################################

if __name__ == '__main__':
    cwd = os.getcwd()
    if checkRenew(): makeKV()
    bool = [False]*7
    is_premium = False
    premium_cookie = {}

    if premium_email != '' and premiun_password != '':
        Premium_login(premium_email, premiun_password)
    AT = Authorization()

    if not os.path.exists('./temp'): os.mkdir('./temp')
    filelist_in_temp = glob.glob('./temp/*.aac')
    for file in filelist_in_temp: os.remove(file)
    if not os.path.exists('./Radio'): os.mkdir('./Radio')

    output_folder = cwd+"/Radio/"
    threads = 4
    TimefreeDownloadApp().run()
