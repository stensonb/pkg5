#!/usr/bin/python2.4
#
# CDDL HEADER START
#
# The contents of this file are subject to the terms of the
# Common Development and Distribution License (the "License").
# You may not use this file except in compliance with the License.
#
# You can obtain a copy of the license at usr/src/OPENSOLARIS.LICENSE
# or http://www.opensolaris.org/os/licensing.
# See the License for the specific language governing permissions
# and limitations under the License.
#
# When distributing Covered Code, include this CDDL HEADER in each
# file and include the License file at usr/src/OPENSOLARIS.LICENSE.
# If applicable, add the following below this CDDL HEADER, with the
# fields enclosed by brackets "[]" replaced with your own identifying
# information: Portions Copyright [yyyy] [name of copyright owner]
#
# CDDL HEADER END
#
# Copyright 2009 Sun Microsystems, Inc.  All rights reserved.
# Use is subject to license terms.
#

import errno
import os
import sys
import time
import pango
import datetime
import traceback
import string
from threading import Thread
try:
        import gobject
        import gtk
        import gtk.glade
        import pygtk
        pygtk.require("2.0")
except ImportError:
        sys.exit(1)
nobe = False
try:
        import libbe as be
except ImportError:
        nobe = True
import pkg.gui.progress as progress
import pkg.client.api_errors as api_errors
import pkg.gui.beadmin as beadm
import pkg.gui.misc as gui_misc
import pkg.gui.enumerations as enumerations

ERROR_FORMAT = "<span color = \"red\">%s</span>"


class InstallUpdate(progress.GuiProgressTracker):
        def __init__(self, list_of_packages, parent, api_o,
            ips_update = False, action = -1, be_name = None, 
            parent_name = "", pkg_list = None, main_window = None,
            icon_confirm_dialog = None, title = None, web_install = False):
                if action == -1:
                        return
                progress.GuiProgressTracker.__init__(self)
                self.web_install = web_install
                self.web_updates_list = None
                api_o.progresstracker = self
                self.api_o = api_o
                self.parent = parent
                self.be_list = None
                self.be_name = be_name
                self.parent_name = parent_name
                self.ipkg_ipkgui_list = pkg_list
                self.icon_confirm_dialog = icon_confirm_dialog
                self.title = title
                self.w_main_window = main_window
                self.ips_update = ips_update
                self.list_of_packages = list_of_packages
                self.action = action
                self.canceling = False
                self.current_stage_name = None
                self.ip = None
                self.operations_done = False
                self.prev_ind_phase = None
                self.prev_pkg = None
                self.progress_stop_timer_running = False
                self.proposed_be_name = None
                self.stages = {
                          1:[_("Preparing..."), _("Preparation")],
                          2:[_("Downloading..."), _("Download")],
                          3:[_("Installing..."), _("Install")],
                         }
                self.stop_progress_bouncing = False
                self.stopped_bouncing_progress = True
                self.update_list = {}
                gladefile = os.path.join(self.parent.application_dir,
                    "usr/share/package-manager/packagemanager.glade")
                w_tree_dialog = gtk.glade.XML(gladefile, "createplandialog")
                w_tree_uaconfirm = gtk.glade.XML(gladefile, "ua_confirm_dialog")
                w_tree_removeconfirm = \
                    gtk.glade.XML(gladefile, "removeconfirmation")
                self.w_dialog = w_tree_dialog.get_widget("createplandialog")
                self.w_expander = w_tree_dialog.get_widget("expander3")
                self.w_cancel_button = w_tree_dialog.get_widget("cancelcreateplan")
                self.w_progressbar = w_tree_dialog.get_widget("createplanprogress")
                self.w_details_textview = w_tree_dialog.get_widget("createplantextview")
                self.w_removeconfirm_dialog = \
                    w_tree_removeconfirm.get_widget("removeconfirmation")
                w_removeproceed_button = w_tree_removeconfirm.get_widget("remove_proceed")
                w_remove_treeview = w_tree_removeconfirm.get_widget("removetreeview")
                w_stage2 = w_tree_dialog.get_widget("stage2")
                self.w_stages_box = w_tree_dialog.get_widget("stages_box")
                self.w_stage1_label = w_tree_dialog.get_widget("label_stage1")
                self.w_stage1_icon = w_tree_dialog.get_widget("icon_stage1")
                self.w_stage2_label = w_tree_dialog.get_widget("label_stage2")
                self.w_stage2_icon = w_tree_dialog.get_widget("icon_stage2")
                self.w_stage3_label = w_tree_dialog.get_widget("label_stage3")
                self.w_stage3_icon = w_tree_dialog.get_widget("icon_stage3")
                self.w_stages_label = w_tree_dialog.get_widget("label_stages")
                self.w_stages_icon = w_tree_dialog.get_widget("icon_stages")
                self.current_stage_label = self.w_stage1_label
                self.current_stage_icon = self.w_stage1_icon
                self.current_stage_label_done = None

                self.done_icon = gui_misc.get_icon(
                    self.parent.icon_theme, "progress_checkmark")
                blank_icon = gui_misc.get_icon(
                    self.parent.icon_theme, "progress_blank")

                self.w_stage1_icon.set_from_pixbuf(blank_icon)
                self.w_stage2_icon.set_from_pixbuf(blank_icon)
                self.w_stage3_icon.set_from_pixbuf(blank_icon)

                infobuffer = self.w_details_textview.get_buffer()
                infobuffer.create_tag("bold", weight=pango.WEIGHT_BOLD)
                infobuffer.create_tag("level1", left_margin=30, right_margin=10)
                infobuffer.create_tag("level2", left_margin=50, right_margin=10)
                self.w_ua_dialog = w_tree_uaconfirm.get_widget("ua_confirm_dialog")
                self.w_ua_error_label = w_tree_uaconfirm.get_widget(
                    "ua_confirm_error_label")
                self.w_ua_proceed_button = w_tree_uaconfirm.get_widget(
                    "ua_proceed_button")
                self.w_ua_be_name_entry = w_tree_uaconfirm.get_widget(
                    "ua_be_name_entry")
                self.w_ua_be_name_box = w_tree_uaconfirm.get_widget(
                    "ua_be_name_box")

                w_ua_proceed_button = w_tree_uaconfirm.get_widget("ua_proceed_button")
                self.w_progressbar.set_pulse_step(0.02)
                try:
                        dic_createplan = \
                            {
                                "on_cancelcreateplan_clicked": \
                                    self.__on_cancelcreateplan_clicked,
                                "on_createplandialog_delete_event": \
                                    self.__on_createplandialog_delete,
                            }
                        dic_uaconfirm = \
                            {
                                "on_ua_cancel_button_clicked": \
                                    self.__on_ua_cancel_button_clicked,
                                "on_ua_proceed_button_clicked": \
                                self.__on_ua_proceed_button_clicked,
                                "on_ua_be_name_entry_changed": \
                                self.__on_ua_be_name_entry_changed,
                                "on_ua_help_button_clicked": \
                                self.__on_ua_help_button_clicked,                                
                            }
                        dic_removeconfirm = \
                            {
                                "on_proceed_button_clicked": \
                                    self.__on_remove_proceed_button_clicked,
                                "on_cancel_button_clicked": \
                                self.__on_remove_cancel_button_clicked,
                            }
                        w_tree_dialog.signal_autoconnect(dic_createplan)
                        w_tree_uaconfirm.signal_autoconnect(dic_uaconfirm)
                        w_tree_removeconfirm.signal_autoconnect(dic_removeconfirm)
                except AttributeError, error:
                        print _("GUI will not respond to any event! %s. "
                            "Check installupdate.py signals") \
                            % error


                self.w_dialog.set_transient_for(self.w_main_window)
                self.w_ua_dialog.set_transient_for(self.w_main_window)
                if self.icon_confirm_dialog != None:  
                        self.w_ua_dialog.set_icon(self.icon_confirm_dialog)

                if self.action == enumerations.REMOVE:
                        #We are not showing the download stage in the main stage list
                        self.stages[3] = [_("Removing..."), _("Remove")]
                        self.w_stage3_label.set_text(self.stages[3][1])
                        w_stage2.hide()
                        self.w_dialog.set_title(_("Remove"))
                        w_removeproceed_button.grab_focus()
                        cell = gtk.CellRendererText()
                        remove_column = gtk.TreeViewColumn('Removed')
                        remove_column.pack_start(cell, True)
                        remove_column.add_attribute(cell, 'text', 0)
                        w_remove_treeview.append_column(remove_column)

                        liststore = gtk.ListStore(str)
                        for sel_pkg in list_of_packages:
                                liststore.append([sel_pkg])
                        w_remove_treeview.set_model(liststore)
                        w_remove_treeview.expand_all()
                        self.w_removeconfirm_dialog.show()

                elif self.action == enumerations.IMAGE_UPDATE:
                        self.w_dialog.set_title(_("Update All"))
                        w_ua_proceed_button.grab_focus()
                        if not self.be_name:
                                if nobe or not "beVerifyBEName" in be.__dict__:
                                        self.w_ua_be_name_box.set_property(
                                            "visible", False)
                                else:
                                        self.__setup_be_list()
                                self.w_ua_dialog.show()
                        else:
                                self.proposed_be_name = self.be_name
                                self.__proceed_with_stages()
                else:
                        if self.title != None:
                                self.w_dialog.set_title(self.title)
                        else:
                                self.w_dialog.set_title(_("Install/Update"))
                        self.__proceed_with_stages()


        def __on_createplandialog_delete(self, widget, event):
                self.__on_cancelcreateplan_clicked(None)
                return True

        def __on_cancelcreateplan_clicked(self, widget):
                '''Handler for signal send by cancel button, which user might press during
                evaluation stage - while the dialog is creating plan'''
                if self.api_o.can_be_canceled():
                        self.canceling = True
                        Thread(target = self.api_o.cancel, args = ()).start()
                        cancel_txt = _("Canceling...")
                        txt = "<b>" + self.current_stage_label_done + " - " \
                            + cancel_txt + "</b>"
                        gobject.idle_add(self.current_stage_label.set_markup, txt)
                        gobject.idle_add(self.current_stage_icon.set_from_stock, 
                            gtk.STOCK_CANCEL, gtk.ICON_SIZE_MENU)
                        gobject.idle_add(self.w_stages_label.set_markup, cancel_txt)
                        self.w_cancel_button.set_sensitive(False)
                if self.operations_done:
                        self.w_dialog.hide()
                        if self.web_install:
                                gobject.idle_add(self.parent.update_package_list, 
                                    self.web_updates_list)
                                return
                        gobject.idle_add(self.parent.update_package_list, None)

        def __on_ua_help_button_clicked(self, widget):
                gui_misc.display_help(self.parent.application_dir, "update_all")
                
        def __on_ua_cancel_button_clicked(self, widget):
                self.w_ua_dialog.hide()
                if self.web_install:
                        gobject.idle_add(self.parent.update_package_list, 
                            self.web_updates_list)
                        return
                gobject.idle_add(self.parent.update_package_list, None)

        def __on_ua_proceed_button_clicked(self, widget):
                proposed_be_name = self.w_ua_be_name_entry.get_text()
                if proposed_be_name != "":
                        self.proposed_be_name = proposed_be_name
                self.w_ua_dialog.hide()
                self.__proceed_with_stages()

        def __setup_be_list(self):
                be_list = be.beList()
                error_code = None
                if len(be_list) > 1 and type(be_list[0]) == type(-1):
                        error_code = be_list[0]
                if error_code != None and error_code == 0:
                        self.be_list = be_list[1]
                elif error_code == None:
                        self.be_list = be_list

                # Now set proposed name in entry field.
                active_name = None
                for bee in self.be_list:
                        name = bee.get("orig_be_name")
                        if name:
                                if bee.get("active"):
                                        active_name = name
                                        break
                if active_name != None:
                        proposed_name = None
                        list = string.rsplit(active_name, '-', 1)
                        if len(list) == 1:
                                proposed_name = self.__construct_be_name(
                                    active_name, 0)
                        else:
                                try:
                                        i = int(list[1])
                                        proposed_name = self.__construct_be_name(
                                            list[0], i)
                                except ValueError:
                                        proposed_name = self.__construct_be_name(
                                            active_name, 0)

                        if proposed_name != None:
                                self.w_ua_be_name_entry.set_text(proposed_name)

                        
        def __construct_be_name(self, name, i):
                in_use = True
                proposed_name = None
                while in_use:
                        i += 1
                        proposed_name = name + '-'  + str(i)
                        in_use = self.__is_be_name_in_use(proposed_name)
                return proposed_name
            
        def __is_be_name_in_use(self, name):
                in_use = False
                if name == "":
                        return in_use
                for bee in self.be_list:
                        be_name = bee.get("orig_be_name")
                        if be_name == name:
                                in_use = True
                                break
                return in_use
 
        def __is_be_name_valid(self, name):
                if name == "":
                        return True
                return be.beVerifyBEName(name) == 0
   
        def __validate_be_name(self, widget):
                name = widget.get_text()
                is_name_valid = self.__is_be_name_valid(name)
                self.w_ua_error_label.hide()
                error_str = None
                if is_name_valid:
                        is_name_in_use = self.__is_be_name_in_use(name)
                        if is_name_in_use:
                                error_str = ERROR_FORMAT % _("BE name is in use")
                else:
                        error_str = ERROR_FORMAT % _("BE name is invalid")
                if error_str != None:
                        self.w_ua_error_label.set_markup(error_str)
                        self.w_ua_error_label.show()
                  
                self.w_ua_proceed_button.set_sensitive(error_str == None)

        def __on_ua_be_name_entry_changed(self, widget):
                self.__validate_be_name(widget)

        def __on_remove_cancel_button_clicked(self, widget):
                self.w_removeconfirm_dialog.hide()

        def __on_remove_proceed_button_clicked(self, widget):
                self.w_removeconfirm_dialog.hide()
                self.__proceed_with_stages()

        def __ipkg_ipkgui_uptodate(self):
                if self.ipkg_ipkgui_list == None:
                        return True
                upgrade_needed, cre = self.api_o.plan_install(
                    self.ipkg_ipkgui_list, filters = [])
                return not upgrade_needed

        def __proceed_with_stages(self):
                self.__start_stage_one()
                self.w_dialog.show()
                Thread(target = self.__proceed_with_stages_thread_ex, 
                    args = ()).start()

        def __proceed_with_stages_thread_ex(self):
                try:
                        try:
                                if self.action == enumerations.IMAGE_UPDATE:
                                        self.__start_substage(
                                            _("Ensuring %s is up to date...") % 
                                            self.parent_name, 
                                            bounce_progress=True)
                                        opensolaris_image = True
                                        ips_uptodate = True
                                        notfound = self.__installed_fmris_from_args(
                                            ["SUNWipkg", "SUNWcs"])
                                        if notfound:
                                                opensolaris_image = False
                                        if opensolaris_image:
                                                ips_uptodate = \
                                                    self.__ipkg_ipkgui_uptodate()
                                        if not ips_uptodate:
                                        #Do the stuff with installing pkg pkg-gui
                                        #and restart in the special mode
                                                self.ips_update = True
                                                self.__proceed_with_ipkg_thread()
                                                return
                                        else:
                                                self.api_o.reset()
                                self.__proceed_with_stages_thread()
                        except (MemoryError, EnvironmentError), __e:
                                if isinstance(__e, EnvironmentError) and \
                                    __e.errno != errno.ENOMEM:
                                        raise
                                msg = pkg.misc.out_of_memory()
                                self.__g_error_stage(msg)
                                return

                except api_errors.CertificateError, e:
                        self.__g_error_stage(str(e))
                        return
                except api_errors.PlanCreationException, e:
                        self.__g_error_stage(str(e))
                        return
                except api_errors.InventoryException, e:
                        msg = _("Inventory exception:\n")
                        if e.illegal:
                                for i in e.illegal:
                                        msg += "\tpkg:\t" + i +"\n"
                        self.__g_error_stage(msg)
                        return
                except api_errors.CatalogRefreshException, e:
                        msg = _("Please check the network "
                            "connection.\nIs the repository accessible?")
                        if e.message and len(e.message) > 0:
                                msg = e.message
                        self.__g_error_stage(msg)
                        return
                except api_errors.TransportError, ex:
                        msg = _("Please check the network "
                            "connection.\nIs the repository accessible?\n\n"
                            "%s") % str(ex)
                        self.__g_error_stage(msg)
                        return
                except api_errors.InvalidDepotResponseException, e:
                        msg = _("\nUnable to contact a valid package depot. "
                            "Please check your network\nsettings and "
                            "attempt to contact the server using a web "
                            "browser.\n\n%s") % str(e)
                        self.__g_error_stage(msg)
                        return
                except api_errors.IpkgOutOfDateException:
                        msg = _("pkg(5) appears to be out of "
                            "date and should be\nupdated before running "
                            "Update All.\nPlease update SUNWipkg package")
                        self.__g_error_stage(msg)
                        return
                except api_errors.NonLeafPackageException, nlpe:
                        msg = _("Cannot remove:\n\t%s\n"
                                "Due to the following packages that "
                                "depend on it:\n") % nlpe[0].get_name()
                        for pkg_a in nlpe[1]:
                                msg += "\t" + pkg_a.get_name() + "\n"
                        self.__g_error_stage(msg)
                        return
                except api_errors.ProblematicPermissionsIndexException, err:
                        msg = str(err)
                        msg += _("\nFailure of consistent use of pfexec or gksu when "
                            "running\n%s is often a source of this problem.") % \
                            self.parent_name
                        msg += _("\nTo rebuild index, please use the terminal command:")
                        msg += _("\n\tpfexec pkg rebuild-index")
                        self.__g_error_stage(msg)
                        return
                except api_errors.CorruptedIndexException:
                        msg = _("There was an error during installation. The search\n"
                            "index is corrupted. You might want try to fix this\n"
                            "problem by running command:\n"
                            "\tpfexec pkg rebuild-index")
                        self.__g_error_stage(msg)
                        return
                except api_errors.ImageUpdateOnLiveImageException:
                        msg = _("This is an Live Image. The install"
                            "\noperation can't be performed.")
                        self.__g_error_stage(msg)
                        return
                except api_errors.PlanMissingException:
                        msg = _("There was an error during installation.\n"
                            "The Plan of the operation is missing and the operation\n"
                            "can't be finished. You might want try to fix this\n"
                            "problem by restarting %s\n") % self.parent_name
                        self.__g_error_stage(msg)
                        return
                except api_errors.ImageplanStateException:
                        msg = _("There was an error during installation.\n"
                            "The State of the image is incorrect and the operation\n"
                            "can't be finished. You might want try to fix this\n"
                            "problem by restarting %s\n") % self.parent_name
                        self.__g_error_stage(msg)
                        return
                except api_errors.CanceledException:
                        gobject.idle_add(self.w_dialog.hide)
                        self.stop_bouncing_progress()
                        return
                except api_errors.BENamingNotSupported:
                        msg = _("Specifying BE Name not supported.\n")
                        self.__g_error_stage(msg)
                        return
                except api_errors.InvalidBENameException:
                        msg = _("Invalid BE Name: %s.\n") % self.proposed_be_name
                        self.__g_error_stage(msg)
                        return
                except api_errors.PermissionsException, pex:
                        msg = str(pex)
                        self.__g_error_stage(msg)
                        return
                except (api_errors.UnableToCopyBE, 
                    api_errors.UnableToMountBE,
                    api_errors.BENameGivenOnDeadBE,
                    api_errors.UnableToRenameBE), ex:
                        msg = str(ex)
                        self.__g_error_stage(msg)
                        return
                except Exception, uex:
                        # We do want to prompt user to load BE admin if there is
                        # not enough disk space. This error can either come as an
                        # error within API exception, see bug #7642 or as a standalone
                        # error, that is why we need to check for both situations.
                        if ("error" in uex.__dict__ and isinstance(uex.error, OSError)
                            and ("args" in uex.error.__dict__ and uex.error.args and \
                            (uex.error.args[0] == errno.EDQUOT or 
                            uex.error.args[0] == errno.ENOSPC))) \
                            or ("args" in uex.__dict__ and uex.args and (uex.args[0] ==
                            errno.EDQUOT or uex.args[0] == errno.ENOSPC)):
                                gobject.idle_add(self.__prompt_to_load_beadm)
                                gobject.idle_add(self.w_dialog.hide)
                                self.stop_bouncing_progress()
                        else:
                                traceback_lines = traceback.format_exc().splitlines()
                                traceback_str = ""
                                for line in traceback_lines: 
                                        traceback_str += line + "\n"
                                self.__g_exception_stage(traceback_str)
                                sys.exc_clear()

        def __proceed_with_ipkg_thread(self):
                self.__start_substage(_("Updating %s") % self.parent_name, 
                    bounce_progress=True)
                self.__afterplan_information()
                self.prev_pkg = None
                self.__start_substage(_("Downloading..."), bounce_progress=False)
                self.api_o.prepare()
                self.__start_substage(_("Executing..."), bounce_progress=False)
                self.api_o.execute_plan()
                gobject.idle_add(self.__operations_done)


        def __proceed_with_stages_thread(self):
                self.__start_substage(
                    _("Gathering package information, please wait..."))
                stuff_todo = self.__plan_stage()
                if stuff_todo:
                        self.__afterplan_information()
                        self.prev_pkg = None
                        # The api.prepare() mostly is downloading the files so we are
                        # Not showing this stage in the main stage dialog. If download 
                        # is necessary, then we are showing it in the details view
                        if not self.action == enumerations.REMOVE:
                                self.__start_stage_two()
                                self.__start_substage(None, 
                                    bounce_progress=False)
                        self.api_o.prepare()
                        self.__start_stage_three()
                        self.__start_substage(None, 
                            bounce_progress=False)
                        self.api_o.execute_plan()
                        gobject.idle_add(self.__operations_done)
                else:
                        if self.web_install:
                                gobject.idle_add(self.w_expander.hide)
                                gobject.idle_add(self.__operations_done, 
                                    _("All packages already installed."))
                                return
                                
                        msg = None
                        if self.action == enumerations.INSTALL_UPDATE:
                                msg = _("Selected package(s) cannot be updated on "
                                "their own.\nClick Update All to update all packages.")
                        elif self.action == enumerations.IMAGE_UPDATE:
                                msg = _("Your system has already been updated.")
                        self.__g_error_stage(msg)

        def __start_stage_one(self):
                self.current_stage_label = self.w_stage1_label
                self.current_stage_icon = self.w_stage1_icon
                self.__start_stage(self.stages.get(1))
                self.update_details_text(self.stages.get(1)[0]+"\n", "bold")
                
        def __start_stage_two(self):
                # End previous stage
                self.__end_stage()
                self.current_stage_label = self.w_stage2_label
                self.current_stage_icon = self.w_stage2_icon
                self.__start_stage(self.stages.get(2))
                self.update_details_text(self.stages.get(2)[0]+"\n", "bold")

        def __start_stage_three(self):
                self.__end_stage()
                self.current_stage_label = self.w_stage3_label
                self.current_stage_icon = self.w_stage3_icon
                self.__start_stage(self.stages.get(3))
                self.update_details_text(self.stages.get(3)[0]+"\n", "bold")

        def __start_stage(self, stage_text):
                self.current_stage_label_done = stage_text[1]
                gobject.idle_add(self.current_stage_label.set_markup, 
                    "<b>"+stage_text[0]+"</b>")
                gobject.idle_add(self.current_stage_icon.set_from_stock, 
                    gtk.STOCK_GO_FORWARD, gtk.ICON_SIZE_MENU)

        def __end_stage(self):
                gobject.idle_add(self.current_stage_label.set_text, 
                    self.current_stage_label_done)
                gobject.idle_add(self.current_stage_icon.set_from_pixbuf, self.done_icon)

        def __g_error_stage(self, msg):
                if msg == None or len(msg) == 0:
                        msg = _("No futher information available") 
                self.operations_done = True
                self.stop_bouncing_progress()
                self.update_details_text(_("\nError:\n"), "bold")
                self.update_details_text("%s" % msg, "level1")
                self.update_details_text("\n")
                txt = "<b>" + self.current_stage_label_done + _(" - Failed </b>")
                gobject.idle_add(self.current_stage_label.set_markup, txt)
                gobject.idle_add(self.current_stage_icon.set_from_stock, 
                    gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_MENU)
                gobject.idle_add(self.w_expander.set_expanded, True)
                gobject.idle_add(self.w_cancel_button.set_sensitive, True)

        def __g_exception_stage(self, tracebk):
                self.operations_done = True
                self.stop_bouncing_progress()
                txt = "<b>" + self.current_stage_label_done + _(" - Failed </b>")
                gobject.idle_add(self.current_stage_label.set_markup, txt)
                gobject.idle_add(self.current_stage_icon.set_from_stock, 
                    gtk.STOCK_DIALOG_ERROR, gtk.ICON_SIZE_MENU)
                msg_1 = _("An unknown error occurred in the %s stage.\n"
                    "Please let the developers know about this problem\n"
                    "by filing a bug together with exception value at:\n"
                    ) % self.current_stage_name
                msg_2 = _("http://defect.opensolaris.org\n\n")
                msg_3 = _("Exception value:\n")
                self.update_details_text(_("\nError:\n"), "bold")
                self.update_details_text("%s" % msg_1, "level1")
                self.update_details_text("%s" % msg_2, "bold", "level2")
                if tracebk:
                        msg = _("Exception traceback:\n")
                        self.update_details_text("%s" % msg, 
                            "bold","level1")
                        self.update_details_text("%s\n" % tracebk, "level2")
                else:
                        msg = _("No futher information available")
                        self.update_details_text("%s\n" % msg, "level2")
                gobject.idle_add(self.w_expander.set_expanded, True)
                gobject.idle_add(self.w_cancel_button.set_sensitive, True)

        def __start_substage(self, text, bounce_progress=True):
                if text:
                        self.update_label_text(text)
                        self.update_details_text(text + "\n")
                if bounce_progress:
                        if self.stopped_bouncing_progress:
                                self.start_bouncing_progress()
                else:
                        self.stop_bouncing_progress()

        def update_label_text(self, markup_text):
                gobject.idle_add(self.__stages_label_set_markup, markup_text)

        def __stages_label_set_markup(self, markup_text):
                if not self.canceling == True:
                        self.w_stages_label.set_markup(markup_text)

        def start_bouncing_progress(self):
                self.stop_progress_bouncing = False
                self.stopped_bouncing_progress = False
                Thread(target = 
                    self.__g_progressdialog_progress_pulse).start()

        def __g_progressdialog_progress_pulse(self):
                while not self.stop_progress_bouncing:
                        gobject.idle_add(self.w_progressbar.pulse)
                        time.sleep(0.1)
                self.stopped_bouncing_progress = True

        def is_progress_bouncing(self):
                return not self.stopped_bouncing_progress

        def stop_bouncing_progress(self):
                if self.is_progress_bouncing():
                        self.stop_progress_bouncing = True

        def update_details_text(self, text, *tags):
                gobject.idle_add(self.__update_details_text, text, *tags)

        def __update_details_text(self, text, *tags):
                buf = self.w_details_textview.get_buffer()
                textiter = buf.get_end_iter()
                if tags:
                        buf.insert_with_tags_by_name(textiter, text, *tags)
                else:
                        buf.insert(textiter, text)
                self.w_details_textview.scroll_to_iter(textiter, 0.0)
                
        def update_progress(self, current, total):
                prog = float(current)/total
                gobject.idle_add(self.w_progressbar.set_fraction, prog)

        def __plan_stage(self):
                '''Function which plans the image'''
                stuff_to_do = False
                if self.action == enumerations.INSTALL_UPDATE:
                        stuff_to_do, cre = self.api_o.plan_install(
                            self.list_of_packages, refresh_catalogs = False, 
                            filters = [])
                        if cre and not cre.succeeded:
                                # cre is either None or a catalog refresh exception 
                                # which was caught while planning.
                                raise api_errors.CatalogRefreshException(None, None, None
                                    ,_("Catalog refresh failed during install."))
                elif self.action == enumerations.REMOVE:
                        plan_uninstall = self.api_o.plan_uninstall
                        stuff_to_do = \
                            plan_uninstall(self.list_of_packages, False, False)
                elif self.action == enumerations.IMAGE_UPDATE:  
                        # we are passing force, since we already checked if the
                        # SUNWipkg and SUNWipkg-gui are up to date.
                        stuff_to_do, opensolaris_image, cre = \
                            self.api_o.plan_update_all(sys.argv[0],
                            refresh_catalogs = False,
                            noexecute = False, force = True,
                            be_name = self.proposed_be_name)
                        if cre and not cre.succeeded:
                                raise api_errors.CatalogRefreshException(None, None, None
                                    ,_("Catalog refresh failed during Update All."))
                return stuff_to_do

        def __operations_done(self, alternate_done_txt = None):
                done_txt = _("Installation completed successfully.")
                if self.action == enumerations.REMOVE:
                        done_txt = _("Packages removed successfully.")
                elif self.action == enumerations.IMAGE_UPDATE:
                        done_txt = _("Packages updated successfully.")
                if alternate_done_txt != None:
                        done_txt = alternate_done_txt
                self.w_stages_box.hide()
                self.w_stages_icon.set_from_stock(
                    gtk.STOCK_OK, gtk.ICON_SIZE_DND)
                self.w_stages_icon.show()
                self.__stages_label_set_markup(done_txt)
                self.__update_details_text("\n"+ done_txt, "bold")
                self.w_cancel_button.set_label("gtk-close")
                self.w_progressbar.hide()
                self.stop_bouncing_progress()
                self.operations_done = True
                if self.parent != None:
                        if not self.web_install and not self.ips_update \
                            and not self.action == enumerations.IMAGE_UPDATE:
                                self.parent.update_package_list(self.update_list)
                        if self.web_install:
                                self.web_updates_list = self.update_list
                if self.ips_update:
                        self.w_dialog.hide()
                        self.parent.restart_after_ips_update(self.proposed_be_name)
                elif self.action == enumerations.IMAGE_UPDATE:
                        self.w_dialog.hide()
                        self.parent.shutdown_after_image_update()

        def __prompt_to_load_beadm(self):
                msgbox = gtk.MessageDialog(parent = self.w_main_window,
                    buttons = gtk.BUTTONS_OK_CANCEL, flags = gtk.DIALOG_MODAL,
                    type = gtk.MESSAGE_ERROR, 
                    message_format = _(
                        "Not enough disk space, the selected action cannot "
                        "be performed.\n\n"
                        "Click OK to manage your existing BEs and free up disk space or "
                        "Cancel to cancel the action."))
                msgbox.set_title(_("Not Enough Disk Space"))
                result = msgbox.run()
                msgbox.destroy()
                if result == gtk.RESPONSE_OK:
                        beadm.Beadmin(self.parent)

        def __afterplan_information(self):
                install_iter = None 
                update_iter = None
                remove_iter = None
                plan = self.api_o.describe().get_changes()
                self.update_details_text("\n")
                for pkg_plan in plan:
                        origin_fmri = pkg_plan[0]
                        destination_fmri = pkg_plan[1]
                        if origin_fmri and destination_fmri:
                                if not update_iter:
                                        update_iter = True
                                        txt = _("Packages To Be Updated:\n")
                                        self.update_details_text(txt, "bold")
                                pkg_a = self.__get_pkgstr_from_pkginfo(destination_fmri)
                                self.update_details_text(pkg_a+"\n", "level1")
                        elif not origin_fmri and destination_fmri:
                                if not install_iter:
                                        install_iter = True
                                        txt = _("Packages To Be Installed:\n")
                                        self.update_details_text(txt, "bold")
                                pkg_a = self.__get_pkgstr_from_pkginfo(destination_fmri)
                                self.update_details_text(pkg_a+"\n", "level1")
                        elif origin_fmri and not destination_fmri:
                                if not remove_iter:
                                        remove_iter = True
                                        txt = _("Packages To Be Removed:\n")
                                        self.update_details_text(txt, "bold")
                                pkg_a = self.__get_pkgstr_from_pkginfo(origin_fmri)
                                self.update_details_text(pkg_a+"\n", "level1")
                self.update_details_text("\n")

        def __get_pkgstr_from_pkginfo(self, pkginfo):
                dt_str = self.get_datetime(pkginfo.packaging_date)
                if not dt_str:
                        dt_str = ""
                s_ver = pkginfo.version
                s_bran = pkginfo.branch
                pkg_name = pkginfo.pkg_stem
                pkg_publisher = pkginfo.publisher
                if not pkg_publisher in self.update_list:
                        self.update_list[pkg_publisher] = []
                pub_list = self.update_list.get(pkg_publisher)
                if not pkg_name in pub_list:
                        pub_list.append(pkg_name)
                l_ver = 0
                version_pref = ""
                while l_ver < len(s_ver) -1:
                        version_pref += "%d%s" % (s_ver[l_ver],".")
                        l_ver += 1
                version_pref += "%d%s" % (s_ver[l_ver],"-")
                l_ver = 0
                version_suf = ""
                if s_bran != None:
                        while l_ver < len(s_bran) -1:
                                version_suf += "%d%s" % (s_bran[l_ver],".")
                                l_ver += 1
                        version_suf += "%d" % s_bran[l_ver]
                pkg_version = version_pref + version_suf + dt_str
                return pkg_name + "@" + pkg_version  

        @staticmethod
        def get_datetime(date_time):
                '''Support function for getting date from the API.'''
                date_tmp = None
                try:
                        date_tmp = time.strptime(date_time, "%a %b %d %H:%M:%S %Y")
                except ValueError:
                        return None
                if date_tmp:
                        date_tmp2 = datetime.datetime(*date_tmp[0:5])        
                        return date_tmp2.strftime(":%m%d")
                return None

        def __installed_fmris_from_args(self, args_f):
                found = []
                notfound = []
                try:
                        for m in self.api_o.img.inventory(args_f):
                                found.append(m[0])
                except api_errors.InventoryException, e:
                        notfound = e.notfound
                return notfound

