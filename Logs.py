from datetime import datetime
import os
def mensaje (txt):
    f = open("Log.txt", "a")
    now = datetime.now()
    f.write(now.strftime("%Y-%m-%d %H:%M:%S ") + txt + '\n')
    f.close()