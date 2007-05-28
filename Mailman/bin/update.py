# Copyright (C) 1998-2007 by the Free Software Foundation, Inc.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301,
# USA.

import os
import md5
import sys
import time
import email
import errno
import shutil
import cPickle
import marshal
import optparse

from Mailman import MailList
from Mailman import Message
from Mailman import Pending
from Mailman import Utils
from Mailman import Version
from Mailman.LockFile import TimeOutError
from Mailman.MemberAdaptor import BYBOUNCE, ENABLED
from Mailman.OldStyleMemberships import OldStyleMemberships
from Mailman.Queue.Switchboard import Switchboard
from Mailman.configuration import config
from Mailman.i18n import _
from Mailman.initialize import initialize

__i18n_templates__ = True

FRESH = 0
NOTFRESH = -1



def parseargs():
    parser = optparse.OptionParser(version=Version.MAILMAN_VERSION,
                                   usage=_("""\
Perform all necessary upgrades.

%prog [options]"""))
    parser.add_option('-f', '--force',
                      default=False, action='store_true', help=_("""\
Force running the upgrade procedures.  Normally, if the version number of the
installed Mailman matches the current version number (or a 'downgrade' is
detected), nothing will be done."""))
    parser.add_option('-C', '--config',
                      help=_('Alternative configuration file to use'))
    opts, args = parser.parse_args()
    if args:
        parser.print_help()
        print >> sys.stderr, _('Unexpected arguments')
        sys.exit(1)
    return parser, opts, args



def calcversions():
    # Returns a tuple of (lastversion, thisversion).  If the last version
    # could not be determined, lastversion will be FRESH or NOTFRESH,
    # depending on whether this installation appears to be fresh or not.  The
    # determining factor is whether there are files in the $var_prefix/logs
    # subdir or not.  The version numbers are HEX_VERSIONs.
    #
    # See if we stored the last updated version
    lastversion = None
    thisversion = Version.HEX_VERSION
    try:
        fp = open(os.path.join(config.DATA_DIR, 'last_mailman_version'))
        data = fp.read()
        fp.close()
        lastversion = int(data, 16)
    except (IOError, ValueError):
        pass
    #
    # try to figure out if this is a fresh install
    if lastversion is None:
        lastversion = FRESH
        try:
            if os.listdir(config.LOG_DIR):
                lastversion = NOTFRESH
        except OSError:
            pass
    return (lastversion, thisversion)



def makeabs(relpath):
    return os.path.join(config.PREFIX, relpath)


def make_varabs(relpath):
    return os.path.join(config.VAR_PREFIX, relpath)



def move_language_templates(mlist):
    listname = mlist.internal_name()
    print _('Fixing language templates: $listname')
    # Mailman 2.1 has a new cascading search for its templates, defined and
    # described in Utils.py:maketext().  Putting templates in the top level
    # templates/ subdir or the lists/<listname> subdir is deprecated and no
    # longer searched..
    #
    # What this means is that most templates can live in the global templates/
    # subdirectory, and only needs to be copied into the list-, vhost-, or
    # site-specific language directories when needed.
    #
    # Also, by default all standard (i.e. English) templates must now live in
    # the templates/en directory.  This update cleans up all the templates,
    # deleting more-specific duplicates (as calculated by md5 checksums) in
    # favor of more-global locations.
    #
    # First, get rid of any lists/<list> template or lists/<list>/en template
    # that is identical to the global templates/* default.
    for gtemplate in os.listdir(os.path.join(config.TEMPLATE_DIR, 'en')):
        # BAW: get rid of old templates, e.g. admlogin.txt and
        # handle_opts.html
        try:
            fp = open(os.path.join(config.TEMPLATE_DIR, gtemplate))
        except IOError, e:
            if e.errno <> errno.ENOENT:
                raise
            # No global template
            continue
        gcksum = md5.new(fp.read()).digest()
        fp.close()
        # Match against the lists/<list>/* template
        try:
            fp = open(os.path.join(mlist.fullpath(), gtemplate))
        except IOError, e:
            if e.errno <> errno.ENOENT:
                raise
        else:
            tcksum = md5.new(fp.read()).digest()
            fp.close()
            if gcksum == tcksum:
                os.unlink(os.path.join(mlist.fullpath(), gtemplate))
        # Match against the lists/<list>/*.prev template
        try:
            fp = open(os.path.join(mlist.fullpath(), gtemplate + '.prev'))
        except IOError, e:
            if e.errno <> errno.ENOENT:
                raise
        else:
            tcksum = md5.new(fp.read()).digest()
            fp.close()
            if gcksum == tcksum:
                os.unlink(os.path.join(mlist.fullpath(), gtemplate + '.prev'))
        # Match against the lists/<list>/en/* templates
        try:
            fp = open(os.path.join(mlist.fullpath(), 'en', gtemplate))
        except IOError, e:
            if e.errno <> errno.ENOENT:
                raise
        else:
            tcksum = md5.new(fp.read()).digest()
            fp.close()
            if gcksum == tcksum:
                os.unlink(os.path.join(mlist.fullpath(), 'en', gtemplate))
        # Match against the templates/* template
        try:
            fp = open(os.path.join(config.TEMPLATE_DIR, gtemplate))
        except IOError, e:
            if e.errno <> errno.ENOENT:
                raise
        else:
            tcksum = md5.new(fp.read()).digest()
            fp.close()
            if gcksum == tcksum:
                os.unlink(os.path.join(config.TEMPLATE_DIR, gtemplate))
        # Match against the templates/*.prev template
        try:
            fp = open(os.path.join(config.TEMPLATE_DIR, gtemplate + '.prev'))
        except IOError, e:
            if e.errno <> errno.ENOENT:
                raise
        else:
            tcksum = md5.new(fp.read()).digest()
            fp.close()
            if gcksum == tcksum:
                os.unlink(os.path.join(config.TEMPLATE_DIR,
                                       gtemplate + '.prev'))



def situate_list(listname):
    # This turns the directory called 'listname' into a directory called
    # 'listname@domain'.  Start by finding out what the domain should be.
    # A list's domain is its email host.
    mlist = MailList.MailList(listname, lock=False, check_version=False)
    fullname = mlist.fqdn_listname
    oldpath = os.path.join(config.VAR_PREFIX, 'lists', listname)
    newpath = os.path.join(config.VAR_PREFIX, 'lists', fullname)
    if os.path.exists(newpath):
        print >> sys.stderr, _('WARNING: could not situate list: $listname')
    else:
        os.rename(oldpath, newpath)
        print _('situated list $listname to $fullname')
    return fullname



def dolist(listname):
    mlist = MailList.MailList(listname, lock=False)
    try:
        mlist.Lock(0.5)
    except TimeOutError:
        print >> sys.stderr, _(
            'WARNING: could not acquire lock for list: $listname')
        return 1
    # Sanity check the invariant that every BYBOUNCE disabled member must have
    # bounce information.  Some earlier betas broke this.  BAW: we're
    # submerging below the MemberAdaptor interface, so skip this if we're not
    # using OldStyleMemberships.
    if isinstance(mlist._memberadaptor, OldStyleMemberships):
        noinfo = {}
        for addr, (reason, when) in mlist.delivery_status.items():
            if reason == BYBOUNCE and not mlist.bounce_info.has_key(addr):
                noinfo[addr] = reason, when
        # What to do about these folks with a BYBOUNCE delivery status and no
        # bounce info?  This number should be very small, and I think it's
        # fine to simple re-enable them and let the bounce machinery
        # re-disable them if necessary.
        n = len(noinfo)
        if n > 0:
            print _(
                'Resetting $n BYBOUNCEs disabled addrs with no bounce info')
            for addr in noinfo.keys():
                mlist.setDeliveryStatus(addr, ENABLED)

    mbox_dir = make_varabs('archives/private/%s.mbox' % (listname))
    mbox_file = make_varabs('archives/private/%s.mbox/%s' % (listname,
                                                             listname))
    o_pub_mbox_file = make_varabs('archives/public/%s' % (listname))
    o_pri_mbox_file = make_varabs('archives/private/%s' % (listname))
    html_dir = o_pri_mbox_file
    o_html_dir = makeabs('public_html/archives/%s' % (listname))
    # Make the mbox directory if it's not there.
    if not os.path.exists(mbox_dir):
        Utils.makedirs(mbox_dir)
    else:
        # This shouldn't happen, but hey, just in case
        if not os.path.isdir(mbox_dir):
            print _("""\
For some reason, $mbox_dir exists as a file.  This won't work with b6, so I'm
renaming it to ${mbox_dir}.tmp and proceeding.""")
            os.rename(mbox_dir, "%s.tmp" % (mbox_dir))
            Utils.makedirs(mbox_dir)
    # Move any existing mboxes around, but watch out for both a public and a
    # private one existing
    if os.path.isfile(o_pri_mbox_file) and os.path.isfile(o_pub_mbox_file):
        if mlist.archive_private:
            print _("""\

$listname has both public and private mbox archives.  Since this list
currently uses private archiving, I'm installing the private mbox archive --
$o_pri_mbox_file -- as the active archive, and renaming
        $o_pub_mbox_file
to
        ${o_pub_mbox_file}.preb6

You can integrate that into the archives if you want by using the 'arch'
script.
""") % (mlist._internal_name, o_pri_mbox_file, o_pub_mbox_file,
        o_pub_mbox_file)
            os.rename(o_pub_mbox_file, "%s.preb6" % (o_pub_mbox_file))
        else:
            print _("""\
$mlist._internal_name has both public and private mbox archives.  Since this
list currently uses public archiving, I'm installing the public mbox file
archive file ($o_pub_mbox_file) as the active one, and renaming
$o_pri_mbox_file to ${o_pri_mbox_file}.preb6

You can integrate that into the archives if you want by using the 'arch'
script.
""")
            os.rename(o_pri_mbox_file, "%s.preb6" % (o_pri_mbox_file))
    # Move private archive mbox there if it's around
    # and take into account all sorts of absurdities
    print _('- updating old private mbox file')
    if os.path.exists(o_pri_mbox_file):
        if os.path.isfile(o_pri_mbox_file):
            os.rename(o_pri_mbox_file, mbox_file)
        elif not os.path.isdir(o_pri_mbox_file):
            newname = "%s.mm_install-dunno_what_this_was_but_its_in_the_way" \
                      % o_pri_mbox_file
            os.rename(o_pri_mbox_file, newname)
            print _("""\
    unknown file in the way, moving
        $o_pri_mbox_file
    to
        $newname""")
        else:
            # directory
            print _("""\
    looks like you have a really recent development installation...
    you're either one brave soul, or you already ran me""")
    # Move public archive mbox there if it's around
    # and take into account all sorts of absurdities.
    print _('- updating old public mbox file')
    if os.path.exists(o_pub_mbox_file):
        if os.path.isfile(o_pub_mbox_file):
            os.rename(o_pub_mbox_file, mbox_file)
        elif not os.path.isdir(o_pub_mbox_file):
            newname = "%s.mm_install-dunno_what_this_was_but_its_in_the_way" \
                      % o_pub_mbox_file
            os.rename(o_pub_mbox_file, newname)
            print _("""\
    unknown file in the way, moving
        $o_pub_mbox_file
    to
        $newname""")
        else: # directory
            print _("""\
    looks like you have a really recent development installation...
    you're either one brave soul, or you already ran me""")
    # Move the html archives there
    if os.path.isdir(o_html_dir):
        os.rename(o_html_dir, html_dir)
        # chmod the html archives
        os.chmod(html_dir, 02775)
    # BAW: Is this still necessary?!
    mlist.Save()
    # Check to see if pre-b4 list-specific templates are around
    # and move them to the new place if there's not already
    # a new one there
    tmpl_dir = os.path.join(config.PREFIX, "templates")
    list_dir = os.path.join(config.PREFIX, "lists")
    b4_tmpl_dir = os.path.join(tmpl_dir, mlist._internal_name)
    new_tmpl_dir = os.path.join(list_dir, mlist._internal_name)
    if os.path.exists(b4_tmpl_dir):
        print _("""\
- This list looks like it might have <= b4 list templates around""")
        for f in os.listdir(b4_tmpl_dir):
            o_tmpl = os.path.join(b4_tmpl_dir, f)
            n_tmpl = os.path.join(new_tmpl_dir, f)
            if os.path.exists(o_tmpl):
                if not os.path.exists(n_tmpl):
                    os.rename(o_tmpl, n_tmpl)
                    print _('- moved $o_tmpl to $n_tmpl')
                else:
                    print _("""\
- both $o_tmpl and $n_tmpl exist, leaving untouched""")
            else:
                print _("""\
- $o_tmpl doesn't exist, leaving untouched""")
    # Move all the templates to the en language subdirectory as required for
    # Mailman 2.1
    move_language_templates(mlist)
    # Avoid eating filehandles with the list lockfiles
    mlist.Unlock()
    return 0



def archive_path_fixer(unused_arg, dir, files):
    # Passed to os.path.walk to fix the perms on old html archives.
    for f in files:
        abs = os.path.join(dir, f)
        if os.path.isdir(abs):
            if f == "database":
                os.chmod(abs, 02770)
            else:
                os.chmod(abs, 02775)
        elif os.path.isfile(abs):
            os.chmod(abs, 0664)


def remove_old_sources(module):
    # Also removes old directories.
    src = '%s/%s' % (config.PREFIX, module)
    pyc = src + "c"
    if os.path.isdir(src):
        print _('removing directory $src and everything underneath')
        shutil.rmtree(src)
    elif os.path.exists(src):
        print _('removing $src')
        try:
            os.unlink(src)
        except os.error, rest:
            print _("Warning: couldn't remove $src -- $rest")
    if module.endswith('.py') and os.path.exists(pyc):
        try:
            os.unlink(pyc)
        except OSError, rest:
            print _("couldn't remove old file $pyc -- $rest")



def update_qfiles():
    print _('updating old qfiles')
    prefix = `time.time()` + '+'
    # Be sure the qfiles/in directory exists (we don't really need the
    # switchboard object, but it's convenient for creating the directory).
    sb = Switchboard(config.INQUEUE_DIR)
    for filename in os.listdir(config.QUEUE_DIR):
        # Updating means just moving the .db and .msg files to qfiles/in where
        # it should be dequeued, converted, and processed normally.
        if os.path.splitext(filename) == '.msg':
            oldmsgfile = os.path.join(config.QUEUE_DIR, filename)
            newmsgfile = os.path.join(config.INQUEUE_DIR, prefix + filename)
            os.rename(oldmsgfile, newmsgfile)
        elif os.path.splitext(filename) == '.db':
            olddbfile = os.path.join(config.QUEUE_DIR, filename)
            newdbfile = os.path.join(config.INQUEUE_DIR, prefix + filename)
            os.rename(olddbfile, newdbfile)
    # Now update for the Mailman 2.1.5 qfile format.  For every filebase in
    # the qfiles/* directories that has both a .pck and a .db file, pull the
    # data out and re-queue them.
    for dirname in os.listdir(config.QUEUE_DIR):
        dirpath = os.path.join(config.QUEUE_DIR, dirname)
        if dirpath == config.BADQUEUE_DIR:
            # The files in qfiles/bad can't possibly be pickles
            continue
        sb = Switchboard(dirpath)
        try:
            for filename in os.listdir(dirpath):
                filepath = os.path.join(dirpath, filename)
                filebase, ext = os.path.splitext(filepath)
                # Handle the .db metadata files as part of the handling of the
                # .pck or .msg message files.
                if ext not in ('.pck', '.msg'):
                    continue
                msg, data = dequeue(filebase)
                if msg is not None and data is not None:
                    sb.enqueue(msg, data)
        except EnvironmentError, e:
            if e.errno <> errno.ENOTDIR:
                raise
            print _('Warning!  Not a directory: $dirpath')



# Implementations taken from the pre-2.1.5 Switchboard
def ext_read(filename):
    fp = open(filename)
    d = marshal.load(fp)
    # Update from version 2 files
    if d.get('version', 0) == 2:
        del d['filebase']
    # Do the reverse conversion (repr -> float)
    for attr in ['received_time']:
        try:
            sval = d[attr]
        except KeyError:
            pass
        else:
            # Do a safe eval by setting up a restricted execution
            # environment.  This may not be strictly necessary since we
            # know they are floats, but it can't hurt.
            d[attr] = eval(sval, {'__builtins__': {}})
    fp.close()
    return d


def dequeue(filebase):
    # Calculate the .db and .msg filenames from the given filebase.
    msgfile = os.path.join(filebase + '.msg')
    pckfile = os.path.join(filebase + '.pck')
    dbfile = os.path.join(filebase + '.db')
    # Now we are going to read the message and metadata for the given
    # filebase.  We want to read things in this order: first, the metadata
    # file to find out whether the message is stored as a pickle or as
    # plain text.  Second, the actual message file.  However, we want to
    # first unlink the message file and then the .db file, because the
    # qrunner only cues off of the .db file
    msg = None
    try:
        data = ext_read(dbfile)
        os.unlink(dbfile)
    except EnvironmentError, e:
        if e.errno <> errno.ENOENT:
            raise
        data = {}
    # Between 2.1b4 and 2.1b5, the `rejection-notice' key in the metadata
    # was renamed to `rejection_notice', since dashes in the keys are not
    # supported in METAFMT_ASCII.
    if data.has_key('rejection-notice'):
        data['rejection_notice'] = data['rejection-notice']
        del data['rejection-notice']
    msgfp = None
    try:
        try:
            msgfp = open(pckfile)
            msg = cPickle.load(msgfp)
            os.unlink(pckfile)
        except EnvironmentError, e:
            if e.errno <> errno.ENOENT: raise
            msgfp = None
            try:
                msgfp = open(msgfile)
                msg = email.message_from_file(msgfp, Message.Message)
                os.unlink(msgfile)
            except EnvironmentError, e:
                if e.errno <> errno.ENOENT: raise
            except (email.Errors.MessageParseError, ValueError), e:
                # This message was unparsable, most likely because its
                # MIME encapsulation was broken.  For now, there's not
                # much we can do about it.
                print _('message is unparsable: $filebase')
                msgfp.close()
                msgfp = None
                if config.QRUNNER_SAVE_BAD_MESSAGES:
                    # Cheapo way to ensure the directory exists w/ the
                    # proper permissions.
                    sb = Switchboard(config.BADQUEUE_DIR)
                    os.rename(msgfile, os.path.join(
                        config.BADQUEUE_DIR, filebase + '.txt'))
                else:
                    os.unlink(msgfile)
                msg = data = None
        except EOFError:
            # For some reason the pckfile was empty.  Just delete it.
            print _('Warning!  Deleting empty .pck file: $pckfile')
            os.unlink(pckfile)
    finally:
        if msgfp:
            msgfp.close()
    return msg, data



def main():
    parser, opts, args = parseargs()
    initialize(opts.config)

    # calculate the versions
    lastversion, thisversion = calcversions()
    hexlversion = hex(lastversion)
    hextversion = hex(thisversion)
    if lastversion == thisversion and not opts.force:
        # nothing to do
        print _('No updates are necessary.')
        sys.exit(0)
    if lastversion > thisversion and not opts.force:
        print _("""\
Downgrade detected, from version $hexlversion to version $hextversion
This is probably not safe.
Exiting.""")
        sys.exit(1)
    print _('Upgrading from version $hexlversion to $hextversion')
    errors = 0
    # get rid of old stuff
    print _('getting rid of old source files')
    for mod in ('Mailman/Archiver.py', 'Mailman/HyperArch.py',
                'Mailman/HyperDatabase.py', 'Mailman/pipermail.py',
                'Mailman/smtplib.py', 'Mailman/Cookie.py',
                'bin/update_to_10b6', 'scripts/mailcmd',
                'scripts/mailowner', 'mail/wrapper', 'Mailman/pythonlib',
                'cgi-bin/archives', 'Mailman/MailCommandHandler'):
        remove_old_sources(mod)
    if not config.list_manager.names:
        print _('no lists == nothing to do, exiting')
        return
    # For people with web archiving, make sure the directories
    # in the archiving are set with proper perms for b6.
    if os.path.isdir("%s/public_html/archives" % config.PREFIX):
        print _("""\
fixing all the perms on your old html archives to work with b6
If your archives are big, this could take a minute or two...""")
        os.path.walk("%s/public_html/archives" % config.PREFIX,
                     archive_path_fixer, "")
        print _('done')
    for listname in config.list_manager.names:
        # With 2.2.0a0, all list names grew an @domain suffix.  If you find a
        # list without that, move it now.
        if not '@' in listname:
            listname = situate_list(listname)
        print _('Updating mailing list: $listname')
        errors += dolist(listname)
        print
    print _('Updating Usenet watermarks')
    wmfile = os.path.join(config.DATA_DIR, 'gate_watermarks')
    try:
        fp = open(wmfile)
    except IOError:
        print _('- nothing to update here')
    else:
        d = marshal.load(fp)
        fp.close()
        for listname in d.keys():
            if listname not in listnames:
                # this list no longer exists
                continue
            mlist = MailList.MailList(listname, lock=0)
            try:
                mlist.Lock(0.5)
            except TimeOutError:
                print >> sys.stderr, _(
                    'WARNING: could not acquire lock for list: $listname')
                errors = errors + 1
            else:
                # Pre 1.0b7 stored 0 in the gate_watermarks file to indicate
                # that no gating had been done yet.  Without coercing this to
                # None, the list could now suddenly get flooded.
                mlist.usenet_watermark = d[listname] or None
                mlist.Save()
                mlist.Unlock()
        os.unlink(wmfile)
        print _('- usenet watermarks updated and gate_watermarks removed')
    # In Mailman 2.1, the qfiles directory has a different structure and a
    # different content.  Also, in Mailman 2.1.5 we collapsed the message
    # files from separate .msg (pickled Message objects) and .db (marshalled
    # dictionaries) to a shared .pck file containing two pickles.
    update_qfiles()
    # This warning was necessary for the upgrade from 1.0b9 to 1.0b10.
    # There's no good way of figuring this out for releases prior to 2.0beta2
    # :(
    if lastversion == NOTFRESH:
        print _("""

NOTE NOTE NOTE NOTE NOTE

    You are upgrading an existing Mailman installation, but I can't tell what
    version you were previously running.

    If you are upgrading from Mailman 1.0b9 or earlier you will need to
    manually update your mailing lists.  For each mailing list you need to
    copy the file templates/options.html lists/<listname>/options.html.

    However, if you have edited this file via the Web interface, you will have
    to merge your changes into this file, otherwise you will lose your
    changes.

NOTE NOTE NOTE NOTE NOTE

""")
    if not errors:
        # Record the version we just upgraded to
        fp = open(os.path.join(config.DATA_DIR, 'last_mailman_version'), 'w')
        fp.write(hex(config.HEX_VERSION) + '\n')
        fp.close()
    else:
        lockdir = config.LOCK_DIR
        print _('''\

ERROR:

The locks for some lists could not be acquired.  This means that either
Mailman was still active when you upgraded, or there were stale locks in the
$lockdir directory.

You must put Mailman into a quiescent state and remove all stale locks, then
re-run "make update" manually.  See the INSTALL and UPGRADE files for details.
''')
