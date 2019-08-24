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

################################################################################
class TimefreeDownloadApp(App):
    def __init__(self, **kwargs):
        super(TimefreeDownloadApp,self).__init__(**kwargs)
        self.title = 'Radio Timefree Download'

    def build(self):
        return MainScreen()

################################################################################

#Radiko.jp authrization
url1,url2 = "https://radiko.jp/v2/api/auth1","https://radiko.jp/v2/api/auth2"
def Authorization():
    headers1 = {'X-Radiko-App':'pc_html5', 'X-Radiko-App-Version':'0.0.1', 'X-Radiko-User':'dummy', 'X-Radiko-Device':'pc'}
    response1 = requests.get(url1, headers = headers1)
    AuthToken, l, o = response1.headers['X-Radiko-AuthToken'], int(response1.headers['X-Radiko-KeyLength']), int(response1.headers['X-Radiko-KeyOffset'])
    fullkey_pc = 'bcd151073c03b352e1ef2fd66c32209da9ca0afa'
    PartialKey = base64.b64encode(fullkey_pc.encode('utf-8')[o:o+l])
    headers2 = {'X-Radiko-AuthToken': AuthToken, 'X-Radiko-PartialKey': PartialKey, 'X-Radiko-User':'dummy','X-Radiko-Device':'pc'}
    response2 = requests.get(url2, headers = headers2)
    return AuthToken

################################################################################

#Find the target program from the radio schedule
def LookForProgram(self,StaID,target,WeekDay):
    dummy_day = date.today()
    if self.ids["a_week_ago"].active: dummy_day = dummy_day - timedelta(days=2)
    if WeekDay != 0:                                                    #曜日指定
        while True:
            weekday = dummy_day.weekday()
            if weekday != WeekDay - 1: dummy_day = dummy_day - timedelta(days=1)
            else: break
    while True:                                                         #番組検索
        day_fomat = '{0:%Y%m%d}'.format(dummy_day)
        xml = urllib.request.urlopen("http://radiko.jp/v3/program/station/date/"+day_fomat+"/"+StaID+".xml")
        soup = BeautifulSoup(xml, "xml").find(string = target)
        if soup == None: dummy_day = dummy_day - timedelta(days=1)
        else: break
    prog = soup.find_parent("prog")
    StartTime, EndTime = prog.get("ft"), prog.get("to")
    return StartTime, EndTime
    #"http://radiko.jp/v3/program/station/weekly/"\+StaID+".xml"

################################################################################

#Download the target
def DL(self,StaID,target,title,WeekDay):
    start = time.time()

    #### LookForProgram ####
    StartTime, EndTime = LookForProgram(self,StaID,target,WeekDay)
    day = StartTime[:8]
    time1, time2 = int(StartTime[8]), int(StartTime[9])
    day = datetime.strptime(day,'%Y%m%d')
    if time1 == 0 and time2 < 5:  day = day - timedelta(days=1)
    day = datetime.strftime(day,'%Y_%m_%d')

    title_full = title+day+'.aac'                              #output file name
    path = output_file+title_full                              #output file path

    #### if the file already exists  ####
    if os.path.exists(path):
        print("\n"+target)
        print("The program already exists.")
    else:
        headers = {'X-Radiko-AuthToken': AT}

        #### get url-chunk-list ####
        url_timefree = "https://radiko.jp/v2/api/ts/playlist.m3u8?station_id="+StaID+"&l=15&ft="+StartTime+"&to="+EndTime
        res_timefree = requests.get(url_timefree, headers = headers)
        m3u8_link = re.search('https://radiko.jp/v2/api/ts/chunklist/[a-zA-Z0-9_/-]{1,61}.m3u8', res_timefree.text)
        if m3u8_link == None:
            print("\n"+title_full)
            print(res_timefree.text + "\n")
            return
        url_chunklist = m3u8_link.group()
        elapsed_time0 = time.time() - start

        #### aria2c ####
        start = time.time()
        print("\n"+title_full)
        print("aria2c...")
        res_chunklist = requests.get(url_chunklist, headers = headers)
        object_list = re.findall('https://media.radiko.jp/sound/[a-zA-Z0-9_/-]{1,61}.aac',res_chunklist.text)
        args = [(i, object_list, AT) for i in range(2)]
        with Pool(processes=threads) as pool:
            pool.map(aria2c_wrapper, args)
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
        #os.remove(path)

        print("\n"+str(os.path.getsize(path)/1000000)+"MB")
        print("set_up:{0}".format(elapsed_time0) + "[sec]")
        print("aria2c:{0}".format(elapsed_time1) + "[sec]")
        print("ffmpeg:{0}".format(elapsed_time2) + "[sec]\n")

        #### delete the chunks in temporary ####
        for file in filelist_in_temp: os.remove(file)

    return

################################################################################
def aria2c_wrapper(args):
    return aria2c_multi(*args)

def aria2c_multi(n,object_list,AT):
    leng = len(object_list)/2
    with open('./temp/list_' +str(n)+'.txt','w') as f:
        i = int(n*leng)
        while i < (n+1)*leng:
            f.write(object_list[i]+ ('\n'))
            i += 1
    cmd_aria2c = "aria2c --console-log-level='error' --download-result='hide' --header='X-Radiko-AuthToken: "+AT+"' -s 16 -j 16 "\
                 "-x 16 -i "+cwd+"/temp/list_"+str(n)+".txt -d "+cwd+"/temp"
    subprocess.call(cmd_aria2c, shell = True)
    return

################################################################################
class MainScreen(Widget):
    def __init__(self):
        super(MainScreen,self).__init__()

    def on_click_Mon(self):
        bool[1] = not bool[1]
        self.ids["ijuin"].active = bool[1]
        self.ids["suda"].active = bool[1]
        return

    def on_click_Tue(self):
        bool[2] = not bool[2]
        self.ids["gen"].active = bool[2]
        self.ids["dcg"].active = bool[2]
        self.ids["bm"].active = bool[2]
        return

    def on_click_Wed(self):
        bool[3] = not bool[3]
        self.ids["giga"].active = bool[3]
        self.ids["fumou"].active = bool[3]
        self.ids["nogiANN"].active = bool[3]
        return

    def on_click_Thu(self):
        bool[4] = not bool[4]
        self.ids["ht"].active = bool[4]
        self.ids["okamura"].active = bool[4]
        self.ids["megane"].active = bool[4]
        return

    def on_click_Fri(self):
        bool[5]= not bool[5]
        self.ids["346"].active = bool[5]
        self.ids["banana"].active = bool[5]
        return

    def on_click_Sta(self):
        bool[6] = not bool[6]
        self.ids["kw"].active = bool[6]
        self.ids["elekata"].active = bool[6]
        return

    def on_click_Sun(self):
        bool[0] = not bool[0]
        return

    def on_click_DL(self):
        if self.ids["suda"].active:
            DL(self,"LFR","菅田将暉のオールナイトニッポン","菅田将暉のオールナイトニッポン_",0)
        if self.ids["ijuin"].active:
            DL(self,"TBS","JUNK 伊集院光・深夜の馬鹿力","伊集院光・深夜の馬鹿力_",0)

        if self.ids["dcg"].active:
            DL(self,"TBS","アルコ＆ピース D.C.GARAGE","アルコ＆ピース_D.C.GARAGE_",0)
        if self.ids["gen"].active:
            DL(self,"LFR","星野源のオールナイトニッポン","星野源のオールナイトニッポン_",0)
        if self.ids["bm"].active:
            DL(self,"TBS","JUNK 爆笑問題カーボーイ","爆笑問題カーボーイ_",0)

        if self.ids["giga"].active:
            DL(self,"TBS","うしろシティ 星のギガボディ","うしろシティ_星のギガボディ_",0)
        if self.ids["nogiANN"].active:
            DL(self,"LFR","乃木坂46のオールナイトニッポン","乃木坂46のオールナイトニッポン_",0)
        if self.ids["fumou"].active:
            DL(self,"TBS","JUNK 山里亮太の不毛な議論","山里亮太の不毛な議論_",0)

        if self.ids["ht"].active:
            DL(self,"TBS","ハライチのターン！","ハライチのターン！_",0)
        if self.ids["okamura"].active:
            DL(self,"LFR","ナインティナイン岡村隆史のオールナイトニッポン","ナインティナイン岡村隆史のオールナイトニッポン_",0)
        if self.ids["megane"].active:
            DL(self,"TBS","JUNK おぎやはぎのメガネびいき","おぎやはぎのメガネびいき_",0)

        if self.ids["346"].active:
            DL(self,"LFR","三四郎のオールナイトニッポン","三四郎のオールナイトニッポン_",0)
        if self.ids["banana"].active:
            DL(self,"TBS","JUNK バナナマンのバナナムーンGOLD","バナナマンのバナナムーンGOLD_",0)

        if self.ids["kw"].active:
            DL(self,"LFR","オードリーのオールナイトニッポン","オードリーのオールナイトニッポン_",0)
        if self.ids["elekata"].active:
            DL(self,"TBS","JUNKサタデー　エレ片のコント太郎","エレ片のコント太郎_",0)

        print("\nAll completed")
        return
################################################################################
if __name__ == '__main__':
    bool = [False]*7
    cwd = os.getcwd()
    AT = Authorization()
    if not os.path.exists('./temp'):
        os.mkdir('./temp')
    filelist_in_temp = glob.glob('./temp/*.aac')
    for file in filelist_in_temp: os.remove(file)
    if not os.path.exists('./Radio'):
        os.mkdir('./Radio')
    output_file = cwd+"/Radio/"
    threads = 4
    TimefreeDownloadApp().run()
