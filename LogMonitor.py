#!/usr/bin/env python

import sys
import os
import datetime
import subprocess
import smtplib
import socket
import re
import errno
import argparse
import importlib

# use this to check for ConfigMaster in python >= 3.4
cm = importlib.find_loader("ConfigMaster")
if cm is None:
    print("ConfigMaster.py is not found! You must add this to PYTHONPATH")
    print("It is found in GitHub under http://github.com/NCAR/ConfigMaster")
    exit(1)

from ConfigMaster import ConfigMaster

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

class Params(ConfigMaster):
  defaultParams = """
#!/usr/bin/env python
import os
 
##############################################################
##  EMAIL OPTIONS
##############################################################
emailList = ["prestop@ucar.edu"]

emailListTruncated = ["prestop@ucar.edu"]

fromEmail = "prestop@ucar.edu"

# Report logs in the summary even if they had no hits.
verboseSummary = False

# A dated directory is created under the destination given
# Set it empty to not have details sent to a file.
sendDetailsToDirs = ["/scratch/WEEKLY/ifigen/LogMonitor"]

# use this to make sure emails are not too long.
# set to zero or negative to get the full message in the email
truncateEmailAfterCharacter = 0

##############################################################
## GREP OPTIONS
##############################################################
searchStrings = ["ERROR","FATAL"]

# number of lines before and after hit to include in report
contextLines = 3

# strings to exclude
excludeStrings = []

##############################################################
## LOG FILE OPTIONS
##############################################################
logDir = "/path/to/log/dir"

# logNameRegex allows you to limit the log files searched to ones that match this regex.
# Leave empty to match all log files.
logNameRegex = ""

# logNameExclude allows you to exclude log files that match this regex.
# Leave empty to not exclude any log files.
logNameExclude = ""

#############################################################
## ADDITIONAL MONITORING OPTIONS
#############################################################

# If true, grep dmesg for segfaults and include that in the list
# of errors
checkForSegFaults = True

# Number of minutes to look back in the dmesg output.
# defaults to one day
dmesgMaxAge = 1440

dmesgIgnoreRegex = ""

"""

cf = Params()

def safe_mkdirs(d):
    if not os.path.exists(d):
        try:
            os.makedirs(d, 0o700)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise

def handle_options():

  parser = argparse.ArgumentParser(description='Parse log directory and generate error report')
  parser.add_argument('-c','--config', help="The configuration file.")
  parser.add_argument('--print_params',action='store_true',
                      help="Generate a sample configuration file.")
  parser.add_argument('-p', '--print_only',action='store_true',
                      help="Print commands only. Doesn't run any scripts")
  args = parser.parse_args()

  cf.init()

  if args.print_params:
    cf.printDefaultParams()
    exit(1)
  
  #find path to config and add to import paths
  if not args.config == None:
    cf.handleConfigFile(args.config)
  
if __name__ == "__main__":
  handle_options()

  reportMsg = ""

  yesterday = datetime.date.today() - datetime.timedelta(1)
  yesterdayYYYYMMDD = "{0:04d}{1:02d}{2:02d}".format(yesterday.year, yesterday.month, yesterday.day)
  reportMsg += "#########################################################<br/>"
  reportMsg += "##                  LOG FILE REPORT                    ##<br/>"
  reportMsg += "#########################################################<br/>"
  reportMsg += "##                  {0:04d}-{1:02d}-{2:02d}                         ##<br/>".format(yesterday.year, yesterday.month, yesterday.day)
  reportMsg += "#########################################################<br/>"

  if (cf.opt['logDir'] == None):
    reportMsg += "logDir is None.  Exciting..."
    exit(1)

  logDir = os.path.join(cf.opt['logDir'],yesterdayYYYYMMDD)
  reportMsg += "Searching " + logDir + "<br/>"
  reportMsg += "----------------------------------------------<br/>"
  print("Searching " + logDir + "<br/>")

  if len(cf.opt['sendDetailsToDirs']) > 0:
    reportMsg += "Report is being saved to files in:<br/>"
    for outDir in cf.opt['sendDetailsToDirs']:
      reportMsg += "\t" + os.path.join(outDir, yesterdayYYYYMMDD) + "<br/>"; 

    reportMsg += "---------------------------------------------<br/>"    
  
  reportMain = ""
  totalHits = 0

  # collect include strings into expression for grep
  srchExpr = ""
  if len(cf.opt['searchStrings']) > 0:
    srchExpr = "'"
    for searchString in cf.opt['searchStrings']:
      srchExpr = srchExpr + searchString + "\|"

    srchExpr = srchExpr[:-2] + "'"  

  print("search expression is " + srchExpr)
  
  # collect exclude strings into expression for grep
  exclExpr = ""
  if len(cf.opt['excludeStrings']) > 0:
    exclExpr = " | grep -v '"
    for excludeString in cf.opt['excludeStrings']:
      exclExpr = exclExpr + excludeString + "\|"

    exclExpr = exclExpr[:-2] + "'"  

  print("exclude expression is " + exclExpr)

  for logFile in os.listdir(logDir):

    if len(cf.opt['logNameRegex']) > 0:
      if not re.search(cf.opt['logNameRegex'],logFile):
        continue
      
    if len(cf.opt['logNameExclude']) > 0:
      if re.search(cf.opt['logNameExclude'],logFile):
        continue
      
    
    reportMain += "========================================<br/>"
    log = os.path.join(logDir,logFile)
    reportMain += "looking at: " + log + "<br/>"
    print("looking at: " + log + "<br/>")
    cmd = "grep -i -C " + str(cf.opt['contextLines']) + " " + srchExpr + " " + log + exclExpr 
    print(cmd)
    grepChild = subprocess.Popen(cmd,stderr=subprocess.PIPE, stdout=subprocess.PIPE, shell=True, universal_newlines=True)
    grepOut = grepChild.communicate()
    grepStdOut = grepOut[0].replace("\n","<br/>")
    grepStdErr = grepOut[1]
    if (len(grepStdOut) > 0):
      reportMain += "----------------------------------------<br/>"
      reportMain += "looking for: " + srchExpr + "<br/>"
      reportMain += grepStdOut + "<br/>"

    for searchString in cf.opt['searchStrings']:
      hits = grepStdOut.lower().count(searchString.lower())
      if hits > 0 or cf.opt['verboseSummary']:
        reportMsg += "SUMMARY: " + str(hits) + " instances of " + searchString + " in " + logFile + "<br/>"
      totalHits += hits

  if cf.opt['checkForSegFaults']:
    segHits = 0
    reportMain += "<br/>==========================================<br/>"
    reportMain += "Looking for segfaults in dmesg:<br/>"
    reportMain += "----------------------------------------<br/>"
    cmd = "dmesg -T | grep segfault"
    grepChild = subprocess.Popen(cmd,stderr=subprocess.PIPE, stdout=subprocess.PIPE, shell=True, universal_newlines=True)
    grepOut = grepChild.communicate()
    grepStdOut = grepOut[0].replace("\n","<br/>")
    grepStdErr = grepOut[1]
    print("stdout: {}".format(grepStdOut))
    if (len(grepStdOut) > 0):
      for line in grepStdOut.splitlines():
        (dateString,sep,garbage) = line[1:].partition("]")
        date = datetime.datetime.strptime(dateString, "%c")
        print("found segfault @ {}".format(dateString))
        td = datetime.datetime.now() - date
        if (td.total_seconds() < (cf.opt['dmesgMaxAge'] * 60)):
          if len(cf.opt['dmesgIgnoreRegex']) > 0:
            if re.search(cf.opt['dmesgIgnoreRegex'],line):
              continue
          print("In time: {}".format(line))
          reportMain += line + "<br/>"
          totalHits += 1
          segHits += 1
          
    reportMsg += "SUMMARY: " + str(segHits) + " segfaults found in dmesg in last " + str(cf.opt['dmesgMaxAge']) + " minutes.<br/>"

  reportMsg += "^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^<br/>"


  reportMsg += reportMain

  # write to a file
  if len(cf.opt['sendDetailsToDirs']) > 0:
    for outDir in cf.opt['sendDetailsToDirs']:
      safe_mkdirs(outDir)
      if not os.access(outDir, os.W_OK | os.X_OK):
        print(outDir + " is not writable, skipping")
        continue 
      dateDir = os.path.join(outDir, yesterdayYYYYMMDD)
      filename = os.path.join(dateDir, "LogMonitor-" + socket.gethostname() + "_(hits:" + str(totalHits) + ")_" + logDir.replace(os.path.sep, '_'))

      
      if not os.path.exists(dateDir):
        try:
          os.makedirs(dateDir)
          os.chmod(dateDir , 0o777)
        except OSError as exc: # Guard against race condition
          if exc.errno != errno.EEXIST:
            raise
      


      with open(filename, "w") as f:
        f.write(reportMsg.replace("<br/>","\n"))

  if cf.opt['truncateEmailAfterCharacter'] > 0 and len(cf.opt['emailListTruncated']) is not 0:
    truncReportMsg = reportMsg[:cf.opt['truncateEmailAfterCharacter']]
    # send email
    mFrom =  cf.opt['fromEmail'];
    mSubject = "Log Monitor (hits: " + str(totalHits) + ") for " +  socket.gethostname() + " " + logDir + " - Truncated"

    msg = MIMEMultipart('alternative')
    msg['Subject'] = mSubject
    msg['From'] = mFrom
    msg['To'] = ", ".join(cf.opt['emailListTruncated'])
    msg.attach(MIMEText(reportMsg, 'html'))
    
    print("sending email: ",msg.as_string())
    s = smtplib.SMTP('localhost')
    s.sendmail(mFrom, cf.opt['emailListTruncated'], msg.as_string())
    s.quit()
    print("done")

  if len(cf.opt['emailList']) is not 0:  
    # send full email
    mFrom =  cf.opt['fromEmail'];
    mSubject = "Log Monitor (hits: " + str(totalHits) + ") for " +  socket.gethostname() + " " + logDir

    msg = MIMEMultipart('alternative')
    msg['Subject'] = mSubject
    msg['From'] = mFrom
    msg['To'] = ", ".join(cf.opt['emailList'])
    msg.attach(MIMEText(reportMsg, 'html'))
    
    print("sending email: ",msg.as_string())
    s = smtplib.SMTP('localhost')
    s.sendmail(mFrom, cf.opt['emailList'], msg.as_string())
    s.quit()
    
  print("done")
    
    
