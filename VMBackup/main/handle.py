#!/usr/bin/env python
#
# VM Backup extension
#
# Copyright 2014 Microsoft Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import array
import base64
import os
import os.path
import re
import json
import string
import subprocess
import sys
import imp
import time
import shlex
import traceback
import xml.parsers.expat
import datetime
try:
    import ConfigParser as ConfigParsers
except ImportError:
    import configparser as ConfigParsers
from threading import Thread
from time import sleep
from os.path import join
from mounts import Mounts
from mounts import Mount
from patch import *
from fsfreezer import FsFreezer
from common import CommonVariables
from parameterparser import ParameterParser
from Utils import HandlerUtil
from Utils import SizeCalculation
from Utils import Status
from freezesnapshotter import FreezeSnapshotter
from backuplogger import Backuplogger
from blobwriter import BlobWriter
from taskidentity import TaskIdentity
from MachineIdentity import MachineIdentity
import ExtensionErrorCodeHelper
from PluginHost import PluginHost
from PluginHost import PluginHostResult

#Main function is the only entrence to this extension handler

def main():
    global MyPatching,backup_logger,hutil,run_result,run_status,error_msg,freezer,freeze_result,snapshot_info_array,total_used_size,size_calculation_failed
    try:
        run_result = CommonVariables.success
        run_status = 'success'
        error_msg = ''
        freeze_result = None
        snapshot_info_array = None
        total_used_size = 0
        size_calculation_failed = False
        HandlerUtil.waagent.LoggerInit('/dev/console','/dev/stdout')
##        HandlerUtil.waagent.Logger.Log((CommonVariables.extension_name) + " started to handle." ) 
        hutil = HandlerUtil.HandlerUtility(HandlerUtil.waagent.Log, HandlerUtil.waagent.Error, CommonVariables.extension_name)
        backup_logger = Backuplogger(hutil)
        MyPatching = GetMyPatching(backup_logger)
        hutil.patching = MyPatching
        for a in sys.argv[1:]:
            if re.match("^([-/]*)(disable)", a):
                disable()
            elif re.match("^([-/]*)(uninstall)", a):
                uninstall()
            elif re.match("^([-/]*)(install)", a):
                install()
            elif re.match("^([-/]*)(enable)", a):
                enable()
            elif re.match("^([-/]*)(update)", a):
                update()
            elif re.match("^([-/]*)(daemon)", a):
                daemon()
    except Exception as e:
        sys.exit(0)

def install():
    global hutil
    hutil.do_parse_context('Install')
    hutil.do_exit(0, 'Install','success','0', 'Install Succeeded')

def timedelta_total_seconds(delta):
    if not hasattr(datetime.timedelta, 'total_seconds'):
        return delta.days * 86400 + delta.seconds
    else:
        return delta.total_seconds()

def status_report_to_file(file_report_msg):
    global backup_logger,hutil
    hutil.write_to_status_file(file_report_msg)
    backup_logger.log("file status report message:",True)
    backup_logger.log(file_report_msg,True)

def status_report_to_blob(blob_report_msg):
    global backup_logger,hutil,para_parser
    try:
        if(para_parser is not None and para_parser.statusBlobUri is not None and para_parser.statusBlobUri != ""):
            blobWriter = BlobWriter(hutil)
            if(blob_report_msg is not None):
                blobWriter.WriteBlob(blob_report_msg,para_parser.statusBlobUri)
                backup_logger.log("blob status report message:",True)
                backup_logger.log(blob_report_msg,True)
            else:
                backup_logger.log("blob_report_msg is none",True)
    except Exception as e:
        err_msg='cannot write status to the status blob'+traceback.format_exc()
        backup_logger.log(err_msg, True, 'Warning')

def get_status_to_report(status, status_code, message, snapshot_info = None):
    global MyPatching,backup_logger,hutil,para_parser,total_used_size,size_calculation_failed
    blob_report_msg = None
    file_report_msg = None
    try:
        if total_used_size == -1 :
            sizeCalculation = SizeCalculation.SizeCalculation(patching = MyPatching , logger = backup_logger)
            total_used_size,size_calculation_failed = sizeCalculation.get_total_used_size()
            number_of_blobs = len(para_parser.blobs)
            maximum_possible_size = number_of_blobs * 1099511627776
            if(total_used_size>maximum_possible_size):
                total_used_size = maximum_possible_size
            backup_logger.log("Assertion Check, total size : {0} ,maximum_possible_size : {1}".format(total_used_size,maximum_possible_size),True)
        if(para_parser is not None and para_parser.statusBlobUri is not None and para_parser.statusBlobUri != ""):
            blob_report_msg, file_report_msg = hutil.do_status_report(operation='Enable',status=status,\
                    status_code=str(status_code),\
                    message=message,\
                    taskId=para_parser.taskId,\
                    commandStartTimeUTCTicks=para_parser.commandStartTimeUTCTicks,\
                    snapshot_info=snapshot_info,\
                    total_size = total_used_size,\
                    failure_flag = size_calculation_failed)
    except Exception as e:
        err_msg='cannot get status report parameters , Exception %s, stack trace: %s' % (str(e), traceback.format_exc())
        backup_logger.log(err_msg, True, 'Warning')
    return blob_report_msg, file_report_msg

def exit_with_commit_log(status,result,error_msg, para_parser):
    global backup_logger
    backup_logger.log(error_msg, True, 'Error')
    if(para_parser is not None and para_parser.logsBlobUri is not None and para_parser.logsBlobUri != ""):
        backup_logger.commit(para_parser.logsBlobUri)
    blob_report_msg, file_report_msg = get_status_to_report(status, result, error_msg, None)
    status_report_to_file(file_report_msg)
    status_report_to_blob(blob_report_msg)
    sys.exit(0)

def exit_if_same_taskId(taskId):
    global backup_logger,hutil,para_parser
    trans_report_msg = None
    taskIdentity = TaskIdentity()
    last_taskId = taskIdentity.stored_identity()
    if(taskId == last_taskId):
        backup_logger.log("TaskId is same as last, so skip with Processed Status, current:" + str(taskId) + "== last:" + str(last_taskId), True)
        status=CommonVariables.status_success 
        hutil.SetExtErrorCode(ExtensionErrorCodeHelper.ExtensionErrorCodeEnum.SuccessAlreadyProcessedInput)
        status_code=CommonVariables.SuccessAlreadyProcessedInput
        message='TaskId AlreadyProcessed nothing to do'
        try:
            if(para_parser is not None):
                blob_report_msg, file_report_msg = hutil.do_status_report(operation='Enable',status=status,\
                        status_code=str(status_code),\
                        message=message,\
                        taskId=taskId,\
                        commandStartTimeUTCTicks=para_parser.commandStartTimeUTCTicks,\
                        snapshot_info=None)
                status_report_to_file(file_report_msg)
        except Exception as e:
            err_msg='cannot write status to the status file, Exception %s, stack trace: %s' % (str(e), traceback.format_exc())
            backup_logger.log(err_msg, True, 'Warning')
        sys.exit(0)

def convert_time(utcTicks):
    return datetime.datetime(1, 1, 1) + datetime.timedelta(microseconds = utcTicks / 10)

def freeze_snapshot(timeout):
    try:
        global hutil,backup_logger,run_result,run_status,error_msg,freezer,freeze_result,para_parser,snapshot_info_array,g_fsfreeze_on
        if(hutil.get_value_from_configfile('doseq') == '2'):
            hutil.set_value_to_configfile('doseq', '1')
        if(hutil.get_value_from_configfile('doseq') != '1'):
            hutil.set_value_to_configfile('doseq', '2')
        freeze_snap_shotter = FreezeSnapshotter(backup_logger, hutil, freezer, g_fsfreeze_on, para_parser)
        backup_logger.log("Calling do snapshot method", True, 'Info')
        run_result, run_status, snapshot_info_array = freeze_snap_shotter.doFreezeSnapshot()
    except Exception as e:
        if(hutil.get_value_from_configfile('doseq') == '2'):
            hutil.set_value_to_configfile('doseq', '0')
        errMsg = 'Failed to do the snapshot with error: %s, stack trace: %s' % (str(e), traceback.format_exc())
        backup_logger.log(errMsg, True, 'Error')
        run_result = CommonVariables.error
        run_status = 'error'
        error_msg = 'Enable failed with exception in safe freeze or snapshot ' 
        hutil.SetExtErrorCode(ExtensionErrorCodeHelper.ExtensionErrorCodeEnum.error)
    #snapshot_done = True

def check_snapshot_array_fail():
    global snapshot_info_array, backup_logger
    snapshot_array_fail = False
    if snapshot_info_array is not None and snapshot_info_array !=[]:
        for snapshot_index in range(len(snapshot_info_array)):
            if(snapshot_info_array[snapshot_index].isSuccessful == False):
                backup_logger.log('T:S  snapshot failed at index ' + str(snapshot_index), True)
                snapshot_array_fail = True
                break
    return snapshot_array_fail

def daemon():
    global MyPatching,backup_logger,hutil,run_result,run_status,error_msg,freezer,para_parser,snapshot_done,snapshot_info_array,g_fsfreeze_on,total_used_size
    #this is using the most recent file timestamp.
    hutil.do_parse_context('Executing')
    freezer = FsFreezer(patching= MyPatching, logger = backup_logger)
    global_error_result = None
    # precheck
    freeze_called = False
    configfile='/etc/azure/vmbackup.conf'
    thread_timeout=str(60)

    #Adding python version to the telemetry
    try:
        python_version_info = sys.version_info
        python_version = str(sys.version_info[0])+ '.'  + str(sys.version_info[1]) + '.'  + str(sys.version_info[2])
        HandlerUtil.HandlerUtility.add_to_telemetery_data("pythonVersion", python_version)
    except Exception as e:
        errMsg = 'Failed to do retrieve python version with error: %s, stack trace: %s' % (str(e), traceback.format_exc())
        backup_logger.log(errMsg, True, 'Error')

    try:
        if(freezer.mounts is not None):
            hutil.partitioncount = len(freezer.mounts.mounts)
        backup_logger.log(" configfile " + str(configfile), True)
        config = ConfigParsers.ConfigParser()
        config.read(configfile)
        if config.has_option('SnapshotThread','timeout'):
            thread_timeout= config.get('SnapshotThread','timeout')
    except Exception as e:
        errMsg='cannot read config file or file not present'
        backup_logger.log(errMsg, True, 'Warning')
    backup_logger.log("final thread timeout" + thread_timeout, True)
    
    snapshot_info_array = None

    try:
        # we need to freeze the file system first
        backup_logger.log('starting daemon', True)
        """
        protectedSettings is the privateConfig passed from Powershell.
        WATCHOUT that, the _context_config are using the most freshest timestamp.
        if the time sync is alive, this should be right.
        """
        if(hutil.is_prev_in_transition()):
            backup_logger.log('retrieving the previous logs for this again inside daemon', True)
            backup_logger.set_prev_log()

        protected_settings = hutil._context._config['runtimeSettings'][0]['handlerSettings'].get('protectedSettings')
        public_settings = hutil._context._config['runtimeSettings'][0]['handlerSettings'].get('publicSettings')
        para_parser = ParameterParser(protected_settings, public_settings, backup_logger)

        commandToExecute = para_parser.commandToExecute
        #validate all the required parameter here
        backup_logger.log(commandToExecute,True)
        if(CommonVariables.iaas_install_command in commandToExecute.lower()):
            backup_logger.log('install succeed.',True)
            run_status = 'success'
            error_msg = 'Install Succeeded'
            run_result = CommonVariables.success
            backup_logger.log(error_msg)
        elif(CommonVariables.iaas_vmbackup_command in commandToExecute.lower()):
            if(para_parser.backup_metadata is None or para_parser.public_config_obj is None or para_parser.private_config_obj is None):
                run_result = CommonVariables.error_parameter
                hutil.SetExtErrorCode(ExtensionErrorCodeHelper.ExtensionErrorCodeEnum.error_parameter)
                run_status = 'error'
                error_msg = 'required field empty or not correct'
                backup_logger.log(error_msg, True, 'Error')
            else:
                backup_logger.log('commandToExecute is ' + commandToExecute, True)
                """
                make sure the log is not doing when the file system is freezed.
                """
                temp_status= 'success'
                temp_result=CommonVariables.ExtensionTempTerminalState
                temp_msg='Transitioning state in extension'
                blob_report_msg, file_report_msg = get_status_to_report(temp_status, temp_result, temp_msg, None)
                if(hutil.is_status_file_exists()):
                    status_report_to_file(file_report_msg)
                status_report_to_blob(blob_report_msg)
                #partial logging before freeze
                if(para_parser is not None and para_parser.logsBlobUri is not None and para_parser.logsBlobUri != ""):
                    backup_logger.commit_to_blob(para_parser.logsBlobUri)
                else:
                    backup_logger.log("the logs blob uri is not there, so do not upload log.")
                backup_logger.log('commandToExecute is ' + commandToExecute, True)

                PluginHostObj = PluginHost(logger=backup_logger)
                PluginHostErrorCode,dobackup,g_fsfreeze_on = PluginHostObj.pre_check()
                doFsConsistentbackup = False
                appconsistentBackup = False

                if not (PluginHostErrorCode == CommonVariables.FailedPrepostPluginhostConfigParsing or
                        PluginHostErrorCode == CommonVariables.FailedPrepostPluginConfigParsing or
                        PluginHostErrorCode == CommonVariables.FailedPrepostPluginhostConfigNotFound or
                        PluginHostErrorCode == CommonVariables.FailedPrepostPluginhostConfigPermissionError or
                        PluginHostErrorCode == CommonVariables.FailedPrepostPluginConfigNotFound):
                    backup_logger.log('App Consistent Consistent Backup Enabled', True)
                    HandlerUtil.HandlerUtility.add_to_telemetery_data("isPrePostEnabled", "true")
                    appconsistentBackup = True

                if(PluginHostErrorCode != CommonVariables.PrePost_PluginStatus_Success):
                    backup_logger.log('Triggering File System Consistent Backup because of error code' + ExtensionErrorCodeHelper.ExtensionErrorCodeHelper.StatusCodeStringBuilder(PluginHostErrorCode), True)
                    doFsConsistentbackup = True

                preResult = PluginHostResult()
                postResult = PluginHostResult()

                if not doFsConsistentbackup:
                    preResult = PluginHostObj.pre_script()
                    dobackup = preResult.continueBackup

                    if(g_fsfreeze_on == False and preResult.anyScriptFailed):
                        dobackup = False

                if dobackup:
                    freeze_snapshot(thread_timeout)

                if not doFsConsistentbackup:
                    postResult = PluginHostObj.post_script()
                    if not postResult.continueBackup:
                        dobackup = False
                
                    if(g_fsfreeze_on == False and postResult.anyScriptFailed):
                        dobackup = False

                if not dobackup:
                    if run_result == CommonVariables.success and PluginHostErrorCode != CommonVariables.PrePost_PluginStatus_Success:
                        run_status = 'error'
                        run_result = PluginHostErrorCode
                        hutil.SetExtErrorCode(PluginHostErrorCode)
                        error_msg = 'Plugin Host Precheck Failed'
                        error_msg = error_msg + ExtensionErrorCodeHelper.ExtensionErrorCodeHelper.StatusCodeStringBuilder(hutil.ExtErrorCode)
                        backup_logger.log(error_msg, True)

                    if run_result == CommonVariables.success:
                        pre_plugin_errors = preResult.errors
                        for error in pre_plugin_errors:
                            if error.errorCode != CommonVariables.PrePost_PluginStatus_Success:
                                run_status = 'error'
                                run_result = error.errorCode
                                hutil.SetExtErrorCode(error.errorCode)
                                error_msg = 'PreScript failed for the plugin ' +  error.pluginName
                                error_msg = error_msg + ExtensionErrorCodeHelper.ExtensionErrorCodeHelper.StatusCodeStringBuilder(hutil.ExtErrorCode)
                                backup_logger.log(error_msg, True)
                                break

                    if run_result == CommonVariables.success:
                        post_plugin_errors = postResult.errors
                        for error in post_plugin_errors:
                            if error.errorCode != CommonVariables.PrePost_PluginStatus_Success:
                                run_status = 'error'
                                run_result = error.errorCode
                                hutil.SetExtErrorCode(error.errorCode)
                                error_msg = 'PostScript failed for the plugin ' +  error.pluginName
                                error_msg = error_msg + ExtensionErrorCodeHelper.ExtensionErrorCodeHelper.StatusCodeStringBuilder(hutil.ExtErrorCode)
                                backup_logger.log(error_msg, True)
                                break

                if appconsistentBackup:
                    if(PluginHostErrorCode != CommonVariables.PrePost_PluginStatus_Success):
                        hutil.SetExtErrorCode(PluginHostErrorCode)
                    pre_plugin_errors = preResult.errors
                    for error in pre_plugin_errors:
                        if error.errorCode != CommonVariables.PrePost_PluginStatus_Success:
                            hutil.SetExtErrorCode(error.errorCode)
                    post_plugin_errors = postResult.errors
                    for error in post_plugin_errors:
                        if error.errorCode != CommonVariables.PrePost_PluginStatus_Success:
                            hutil.SetExtErrorCode(error.errorCode)

                if run_result == CommonVariables.success and not doFsConsistentbackup and not (preResult.anyScriptFailed or postResult.anyScriptFailed):
                    run_status = 'success'
                    run_result = CommonVariables.success_appconsistent
                    hutil.SetExtErrorCode(ExtensionErrorCodeHelper.ExtensionErrorCodeEnum.success_appconsistent)
                    error_msg = 'Enable Succeeded with App Consistent Snapshot'
                    backup_logger.log(error_msg, True)

        else:
            run_status = 'error'
            run_result = CommonVariables.error_parameter
            hutil.SetExtErrorCode(ExtensionErrorCodeHelper.ExtensionErrorCodeEnum.error_parameter)
            error_msg = 'command is not correct'
            backup_logger.log(error_msg, True, 'Error')
    except Exception as e:
        errMsg = 'Failed to enable the extension with error: %s, stack trace: %s' % (str(e), traceback.format_exc())
        backup_logger.log(errMsg, True, 'Error')
        global_error_result = e

    """
    we do the final report here to get rid of the complex logic to handle the logging when file system be freezed issue.
    """
    try:
        if(global_error_result is not None):
            if(hasattr(global_error_result,'errno') and global_error_result.errno == 2):
                run_result = CommonVariables.error_12
                hutil.SetExtErrorCode(ExtensionErrorCodeHelper.ExtensionErrorCodeEnum.error_12)
            elif(ExtensionErrorCodeHelper.ExtensionErrorCodeHelper.ExtensionErrorCodeNameDict[ExtensionErrorCodeHelper.ExtensionErrorCodeEnum.error_parameter] in str(global_error_result)):
                run_result = CommonVariables.error_parameter
                hutil.SetExtErrorCode(ExtensionErrorCodeHelper.ExtensionErrorCodeEnum.error_parameter)
            elif(para_parser is None):
                run_result = CommonVariables.error_parameter
                hutil.SetExtErrorCode(ExtensionErrorCodeHelper.ExtensionErrorCodeEnum.error_parameter)
            else:
                run_result = CommonVariables.error
                hutil.SetExtErrorCode(ExtensionErrorCodeHelper.ExtensionErrorCodeEnum.error)
            run_status = 'error'
            error_msg  += ('Enable failed.' + str(global_error_result))
        status_report_msg = None
        HandlerUtil.HandlerUtility.add_to_telemetery_data("extErrorCode", str(ExtensionErrorCodeHelper.ExtensionErrorCodeHelper.ExtensionErrorCodeNameDict[hutil.ExtErrorCode]))
        total_used_size = -1
        blob_report_msg, file_report_msg = get_status_to_report(run_status,run_result,error_msg, snapshot_info_array)
        if(hutil.is_status_file_exists()):
            status_report_to_file(file_report_msg)
        status_report_to_blob(blob_report_msg)
    except Exception as e:
        errMsg = 'Failed to log status in extension'
        backup_logger.log(errMsg, True, 'Error')
    if(para_parser is not None and para_parser.logsBlobUri is not None and para_parser.logsBlobUri != ""):
        backup_logger.commit(para_parser.logsBlobUri)
    else:
        backup_logger.log("the logs blob uri is not there, so do not upload log.")
        backup_logger.commit_to_local()

    sys.exit(0)

def uninstall():
    hutil.do_parse_context('Uninstall')
    hutil.do_exit(0,'Uninstall','success','0', 'Uninstall succeeded')

def disable():
    hutil.do_parse_context('Disable')
    hutil.do_exit(0,'Disable','success','0', 'Disable Succeeded')

def update():
    hutil.do_parse_context('Upadate')
    hutil.do_exit(0,'Update','success','0', 'Update Succeeded')

def enable():
    global backup_logger,hutil,error_msg,para_parser
    hutil.do_parse_context('Enable')
    try:
        backup_logger.log('starting to enable', True)
        # handle the restoring scenario.
        mi = MachineIdentity()
        stored_identity = mi.stored_identity()
        if(stored_identity is None):
            mi.save_identity()
        else:
            current_identity = mi.current_identity()
            if(current_identity != stored_identity):
                current_seq_no = -1
                backup_logger.log("machine identity not same, set current_seq_no to " + str(current_seq_no) + " " + str(stored_identity) + " " + str(current_identity), True)
                hutil.set_last_seq(current_seq_no)
                mi.save_identity()
        hutil.exit_if_same_seq()

        """
        protectedSettings is the privateConfig passed from Powershell.
        WATCHOUT that, the _context_config are using the most freshest timestamp.
        if the time sync is alive, this should be right.
        """
        protected_settings = hutil._context._config['runtimeSettings'][0]['handlerSettings'].get('protectedSettings')
        public_settings = hutil._context._config['runtimeSettings'][0]['handlerSettings'].get('publicSettings')
        para_parser = ParameterParser(protected_settings, public_settings, backup_logger)

        if(bool(public_settings) and not protected_settings): #Protected settings decryption failed case
            error_msg = "unable to load certificate"
            hutil.SetExtErrorCode(ExtensionErrorCodeHelper.ExtensionErrorCodeEnum.FailedHandlerGuestAgentCertificateNotFound)
            temp_result=CommonVariables.FailedHandlerGuestAgentCertificateNotFound
            temp_status= 'error'
            exit_with_commit_log(temp_status, temp_result,error_msg, para_parser)

        if(para_parser.commandStartTimeUTCTicks is not None and para_parser.commandStartTimeUTCTicks != ""):
            utcTicksLong = int(para_parser.commandStartTimeUTCTicks)
            backup_logger.log('utcTicks in long format' + str(utcTicksLong), True)
            commandStartTime = convert_time(utcTicksLong)
            utcNow = datetime.datetime.utcnow()
            backup_logger.log('command start time is ' + str(commandStartTime) + " and utcNow is " + str(utcNow), True)
            timespan = utcNow - commandStartTime
            MAX_TIMESPAN = 150 * 60 # in seconds
            # handle the machine identity for the restoration scenario.
            total_span_in_seconds = timedelta_total_seconds(timespan)
            backup_logger.log('timespan is ' + str(timespan) + ' ' + str(total_span_in_seconds))

        if(para_parser.taskId is not None and para_parser.taskId != ""):
            backup_logger.log('taskId: ' + str(para_parser.taskId), True)
            exit_if_same_taskId(para_parser.taskId) 
            taskIdentity = TaskIdentity()
            taskIdentity.save_identity(para_parser.taskId)
        hutil.save_seq()
        temp_status= 'transitioning'
        temp_result=CommonVariables.success
        temp_msg='Transitioning state in enable'
        blob_report_msg, file_report_msg = get_status_to_report(temp_status, temp_result, temp_msg, None)
        file_status_upload_thread=Thread(target=status_report_to_file, args=(file_report_msg,))
        file_status_upload_thread.start()
        blob_status_upload_thread=Thread(target=status_report_to_blob, args=(blob_report_msg,))
        blob_status_upload_thread.start()
        if(hutil.is_prev_in_transition()):
            backup_logger.log('retrieving the previous logs for this', True)
            backup_logger.set_prev_log()
        if(para_parser is not None and para_parser.logsBlobUri is not None and para_parser.logsBlobUri != ""):
            log_upload_thread=Thread(target=thread_for_log_upload)
            log_upload_thread.start()
            log_upload_thread.join(60)
        file_status_upload_thread.join(30)
        blob_status_upload_thread.join(60)
        start_daemon()
        sys.exit(0)
    except Exception as e:
        errMsg = 'Failed to call the daemon with error: %s, stack trace: %s' % (str(e), traceback.format_exc())
        backup_logger.log(errMsg, True, 'Error')
        global_error_result = e
        temp_status= 'error'
        temp_result=CommonVariables.error
        temp_errorCode=ExtensionErrorCodeHelper.ExtensionErrorCodeEnum.error

        if(ExtensionErrorCodeHelper.ExtensionErrorCodeHelper.ExtensionErrorCodeNameDict[ExtensionErrorCodeHelper.ExtensionErrorCodeEnum.error_parameter] in str(global_error_result)):
            temp_result = CommonVariables.error_parameter
            temp_errorCode = ExtensionErrorCodeHelper.ExtensionErrorCodeEnum.error_parameter
        
        hutil.SetExtErrorCode(temp_errorCode)
        error_msg = 'Failed to call the daemon'
        exit_with_commit_log(temp_status, temp_result,error_msg, para_parser)

def thread_for_log_upload():
    global para_parser,backup_logger
    backup_logger.commit(para_parser.logsBlobUri)

def start_daemon():
    args = [os.path.join(os.getcwd(), "main/handle.sh"), "daemon"]
    backup_logger.log("start_daemon with args: {0}".format(args), True)
    #This process will start a new background process by calling
    #    handle.py -daemon
    #to run the script and will exit itself immediatelly.

    #Redirect stdout and stderr to /dev/null.  Otherwise daemon process will
    #throw Broke pipe exeception when parent process exit.
    devnull = open(os.devnull, 'w')
    child = subprocess.Popen(args, stdout=devnull, stderr=devnull)

if __name__ == '__main__' :
    main()
