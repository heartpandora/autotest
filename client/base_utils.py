"""
DO NOT import this file directly - import client/bin/utils.py,
which will mix this in

Convenience functions for use by tests or whomever.

Note that this file is mixed in by utils.py - note very carefully the
precedence order defined there
"""
import os, shutil, sys, signal, commands, pickle, glob, statvfs
import math, re, string, fnmatch, logging
from autotest_lib.client.common_lib import error, utils, magic


def grep(pattern, file):
    """
    This is mainly to fix the return code inversion from grep
    Also handles compressed files.

    returns 1 if the pattern is present in the file, 0 if not.
    """
    command = 'grep "%s" > /dev/null' % pattern
    ret = cat_file_to_cmd(file, command, ignore_status=True)
    return not ret


def difflist(list1, list2):
    """returns items in list2 that are not in list1"""
    diff = [];
    for x in list2:
        if x not in list1:
            diff.append(x)
    return diff


def cat_file_to_cmd(file, command, ignore_status=0, return_output=False):
    """
    equivalent to 'cat file | command' but knows to use
    zcat or bzcat if appropriate
    """
    if not os.path.isfile(file):
        raise NameError('invalid file %s to cat to command %s'
                % (file, command))

    if return_output:
        run_cmd = utils.system_output
    else:
        run_cmd = utils.system

    if magic.guess_type(file) == 'application/x-bzip2':
        cat = 'bzcat'
    elif magic.guess_type(file) == 'application/x-gzip':
        cat = 'zcat'
    else:
        cat = 'cat'
    return run_cmd('%s %s | %s' % (cat, file, command),
                                                    ignore_status=ignore_status)


def extract_tarball_to_dir(tarball, dir):
    """
    Extract a tarball to a specified directory name instead of whatever
    the top level of a tarball is - useful for versioned directory names, etc
    """
    if os.path.exists(dir):
        if os.path.isdir(dir):
            shutil.rmtree(dir)
        else:
            os.remove(dir)
    pwd = os.getcwd()
    os.chdir(os.path.dirname(os.path.abspath(dir)))
    newdir = extract_tarball(tarball)
    os.rename(newdir, dir)
    os.chdir(pwd)


def extract_tarball(tarball):
    """Returns the directory extracted by the tarball."""
    extracted = cat_file_to_cmd(tarball, 'tar xvf - 2>/dev/null',
                                    return_output=True).splitlines()

    dir = None

    for line in extracted:
        line = re.sub(r'^./', '', line)
        if not line or line == '.':
            continue
        topdir = line.split('/')[0]
        if os.path.isdir(topdir):
            if dir:
                assert(dir == topdir)
            else:
                dir = topdir
    if dir:
        return dir
    else:
        raise NameError('extracting tarball produced no dir')


def hash_file(filename, size=None, method="md5"):
    """
    Calculate the hash of filename.
    If size is not None, limit to first size bytes.
    Throw exception if something is wrong with filename.
    Can be also implemented with bash one-liner (assuming size%1024==0):
    dd if=filename bs=1024 count=size/1024 | sha1sum -

    @param filename: Path of the file that will have its hash calculated.
    @param method: Method used to calculate the hash. Supported methods:
            * md5
            * sha1
    @returns: Hash of the file, if something goes wrong, return None.
    """
    chunksize = 4096
    fsize = os.path.getsize(filename)

    if not size or size > fsize:
        size = fsize
    f = open(filename, 'rb')

    try:
        hash = utils.hash(method)
    except ValueError:
        logging.error("Unknown hash type %s, returning None" % method)

    while size > 0:
        if chunksize > size:
            chunksize = size
        data = f.read(chunksize)
        if len(data) == 0:
            logging.debug("Nothing left to read but size=%d" % size)
            break
        hash.update(data)
        size -= len(data)
    f.close()
    return hash.hexdigest()


def unmap_url_cache(cachedir, url, expected_hash, method="md5"):
    """
    Downloads a file from a URL to a cache directory. If the file is already
    at the expected position and has the expected hash, let's not download it
    again.

    @param cachedir: Directory that might hold a copy of the file we want to
            download.
    @param url: URL for the file we want to download.
    @param expected_hash: Hash string that we expect the file downloaded to
            have.
    @param method: Method used to calculate the hash string (md5, sha1).
    """
    # Let's convert cachedir to a canonical path, if it's not already
    cachedir = os.path.realpath(cachedir)
    if not os.path.isdir(cachedir):
        try:
            os.makedirs(cachedir)
        except Exception:
            raise ValueError('Could not create cache directory %s' % cachedir)
    file_from_url = os.path.basename(url)
    file_local_path = os.path.join(cachedir, file_from_url)

    file_hash = None
    failure_counter = 0
    while not file_hash == expected_hash:
        if os.path.isfile(file_local_path):
            file_hash = hash_file(file_local_path, method)
            if file_hash == expected_hash:
                # File is already at the expected position and ready to go
                src = file_from_url
            else:
                # Let's download the package again, it's corrupted...
                logging.error("Seems that file %s is corrupted, trying to "
                              "download it again" % file_from_url)
                src = url
                failure_counter += 1
        else:
            # File is not there, let's download it
            src = url
        if failure_counter > 1:
            raise EnvironmentError("Consistently failed to download the "
                                   "package %s. Aborting further download "
                                   "attempts. This might mean either the "
                                   "network connection has problems or the "
                                   "expected hash string that was determined "
                                   "for this file is wrong" % file_from_url)
        file_path = utils.unmap_url(cachedir, src, cachedir)

    return file_path


def force_copy(src, dest):
    """Replace dest with a new copy of src, even if it exists"""
    if os.path.isfile(dest):
        os.remove(dest)
    if os.path.isdir(dest):
        dest = os.path.join(dest, os.path.basename(src))
    shutil.copyfile(src, dest)
    return dest


def force_link(src, dest):
    """Link src to dest, overwriting it if it exists"""
    return utils.system("ln -sf %s %s" % (src, dest))


def file_contains_pattern(file, pattern):
    """Return true if file contains the specified egrep pattern"""
    if not os.path.isfile(file):
        raise NameError('file %s does not exist' % file)
    return not utils.system('egrep -q "' + pattern + '" ' + file, ignore_status=True)


def list_grep(list, pattern):
    """True if any item in list matches the specified pattern."""
    compiled = re.compile(pattern)
    for line in list:
        match = compiled.search(line)
        if (match):
            return 1
    return 0


def get_os_vendor():
    """Try to guess what's the os vendor
    """
    if os.path.isfile('/etc/SuSE-release'):
        return 'SUSE'

    issue = '/etc/issue'

    if not os.path.isfile(issue):
        return 'Unknown'

    if file_contains_pattern(issue, 'Red Hat'):
        return 'Red Hat'
    elif file_contains_pattern(issue, 'Fedora'):
        return 'Fedora Core'
    elif file_contains_pattern(issue, 'SUSE'):
        return 'SUSE'
    elif file_contains_pattern(issue, 'Ubuntu'):
        return 'Ubuntu'
    elif file_contains_pattern(issue, 'Debian'):
        return 'Debian'
    else:
        return 'Unknown'


def get_cc():
    try:
        return os.environ['CC']
    except KeyError:
        return 'gcc'


def get_vmlinux():
    """Return the full path to vmlinux

    Ahem. This is crap. Pray harder. Bad Martin.
    """
    vmlinux = '/boot/vmlinux-%s' % utils.system_output('uname -r')
    if os.path.isfile(vmlinux):
        return vmlinux
    vmlinux = '/lib/modules/%s/build/vmlinux' % utils.system_output('uname -r')
    if os.path.isfile(vmlinux):
        return vmlinux
    return None


def get_systemmap():
    """Return the full path to System.map

    Ahem. This is crap. Pray harder. Bad Martin.
    """
    map = '/boot/System.map-%s' % utils.system_output('uname -r')
    if os.path.isfile(map):
        return map
    map = '/lib/modules/%s/build/System.map' % utils.system_output('uname -r')
    if os.path.isfile(map):
        return map
    return None


def get_modules_dir():
    """Return the modules dir for the running kernel version"""
    kernel_version = utils.system_output('uname -r')
    return '/lib/modules/%s/kernel' % kernel_version


def get_cpu_arch():
    """Work out which CPU architecture we're running on"""
    f = open('/proc/cpuinfo', 'r')
    cpuinfo = f.readlines()
    f.close()
    if list_grep(cpuinfo, '^cpu.*(RS64|POWER3|Broadband Engine)'):
        return 'power'
    elif list_grep(cpuinfo, '^cpu.*POWER4'):
        return 'power4'
    elif list_grep(cpuinfo, '^cpu.*POWER5'):
        return 'power5'
    elif list_grep(cpuinfo, '^cpu.*POWER6'):
        return 'power6'
    elif list_grep(cpuinfo, '^cpu.*POWER7'):
        return 'power7'
    elif list_grep(cpuinfo, '^cpu.*PPC970'):
        return 'power970'
    elif list_grep(cpuinfo, 'ARM'):
        return 'arm'
    elif list_grep(cpuinfo, '^flags.*:.* lm .*'):
        return 'x86_64'
    else:
        return 'i386'


def get_current_kernel_arch():
    """Get the machine architecture, now just a wrap of 'uname -m'."""
    return os.popen('uname -m').read().rstrip()


def get_file_arch(filename):
    # -L means follow symlinks
    file_data = utils.system_output('file -L ' + filename)
    if file_data.count('80386'):
        return 'i386'
    return None


def count_cpus():
    """number of CPUs in the local machine according to /proc/cpuinfo"""
    f = file('/proc/cpuinfo', 'r')
    cpus = 0
    for line in f.readlines():
        if line.lower().startswith('processor'):
            cpus += 1
    return cpus


# Returns total memory in kb
def read_from_meminfo(key):
    cmd_result = utils.run('grep %s /proc/meminfo' % key, verbose=False)
    meminfo = cmd_result.stdout
    return int(re.search(r'\d+', meminfo).group(0))


def memtotal():
    return read_from_meminfo('MemTotal')


def freememtotal():
    return read_from_meminfo('MemFree')


def rounded_memtotal():
    # Get total of all physical mem, in kbytes
    usable_kbytes = memtotal()
    # usable_kbytes is system's usable DRAM in kbytes,
    #   as reported by memtotal() from device /proc/meminfo memtotal
    #   after Linux deducts 1.5% to 5.1% for system table overhead
    # Undo the unknown actual deduction by rounding up
    #   to next small multiple of a big power-of-two
    #   eg  12GB - 5.1% gets rounded back up to 12GB
    mindeduct = 0.015  # 1.5 percent
    maxdeduct = 0.055  # 5.5 percent
    # deduction range 1.5% .. 5.5% supports physical mem sizes
    #    6GB .. 12GB in steps of .5GB
    #   12GB .. 24GB in steps of 1 GB
    #   24GB .. 48GB in steps of 2 GB ...
    # Finer granularity in physical mem sizes would require
    #   tighter spread between min and max possible deductions

    # increase mem size by at least min deduction, without rounding
    min_kbytes   = int(usable_kbytes / (1.0 - mindeduct))
    # increase mem size further by 2**n rounding, by 0..roundKb or more
    round_kbytes = int(usable_kbytes / (1.0 - maxdeduct)) - min_kbytes
    # find least binary roundup 2**n that covers worst-cast roundKb
    mod2n = 1 << int(math.ceil(math.log(round_kbytes, 2)))
    # have round_kbytes <= mod2n < round_kbytes*2
    # round min_kbytes up to next multiple of mod2n
    phys_kbytes = min_kbytes + mod2n - 1
    phys_kbytes = phys_kbytes - (phys_kbytes % mod2n)  # clear low bits
    return phys_kbytes


def sysctl(key, value=None):
    """Generic implementation of sysctl, to read and write.

    @param key: A location under /proc/sys
    @param value: If not None, a value to write into the sysctl.

    @return The single-line sysctl value as a string.
    """
    path = '/proc/sys/%s' % key
    if value is not None:
        utils.write_one_line(path, str(value))
    return utils.read_one_line(path)


def sysctl_kernel(key, value=None):
    """(Very) partial implementation of sysctl, for kernel params"""
    if value is not None:
        # write
        utils.write_one_line('/proc/sys/kernel/%s' % key, str(value))
    else:
        # read
        out = utils.read_one_line('/proc/sys/kernel/%s' % key)
        return int(re.search(r'\d+', out).group(0))


def _convert_exit_status(sts):
    if os.WIFSIGNALED(sts):
        return -os.WTERMSIG(sts)
    elif os.WIFEXITED(sts):
        return os.WEXITSTATUS(sts)
    else:
        # impossible?
        raise RuntimeError("Unknown exit status %d!" % sts)


def where_art_thy_filehandles():
    """Dump the current list of filehandles"""
    os.system("ls -l /proc/%d/fd >> /dev/tty" % os.getpid())


def print_to_tty(string):
    """Output string straight to the tty"""
    open('/dev/tty', 'w').write(string + '\n')


def dump_object(object):
    """Dump an object's attributes and methods

    kind of like dir()
    """
    for item in object.__dict__.iteritems():
        print item
        try:
            (key, value) = item
            dump_object(value)
        except Exception:
            continue


def environ(env_key):
    """return the requested environment variable, or '' if unset"""
    if (os.environ.has_key(env_key)):
        return os.environ[env_key]
    else:
        return ''


def prepend_path(newpath, oldpath):
    """prepend newpath to oldpath"""
    if (oldpath):
        return newpath + ':' + oldpath
    else:
        return newpath


def append_path(oldpath, newpath):
    """append newpath to oldpath"""
    if (oldpath):
        return oldpath + ':' + newpath
    else:
        return newpath


def avgtime_print(dir):
    """ Calculate some benchmarking statistics.
        Input is a directory containing a file called 'time'.
        File contains one-per-line results of /usr/bin/time.
        Output is average Elapsed, User, and System time in seconds,
          and average CPU percentage.
    """
    f = open(dir + "/time")
    user = system = elapsed = cpu = count = 0
    r = re.compile('([\d\.]*)user ([\d\.]*)system (\d*):([\d\.]*)elapsed (\d*)%CPU')
    for line in f.readlines():
        try:
            s = r.match(line);
            user += float(s.group(1))
            system += float(s.group(2))
            elapsed += (float(s.group(3)) * 60) + float(s.group(4))
            cpu += float(s.group(5))
            count += 1
        except Exception:
            raise ValueError("badly formatted times")

    f.close()
    return "Elapsed: %0.2fs User: %0.2fs System: %0.2fs CPU: %0.0f%%" % \
          (elapsed/count, user/count, system/count, cpu/count)


def running_config():
    """
    Return path of config file of the currently running kernel
    """
    version = utils.system_output('uname -r')
    for config in ('/proc/config.gz', \
                   '/boot/config-%s' % version,
                   '/lib/modules/%s/build/.config' % version):
        if os.path.isfile(config):
            return config
    return None


def check_for_kernel_feature(feature):
    config = running_config()

    if not config:
        raise TypeError("Can't find kernel config file")

    if magic.guess_type(config) == 'application/x-gzip':
        grep = 'zgrep'
    else:
        grep = 'grep'
    grep += ' ^CONFIG_%s= %s' % (feature, config)

    if not utils.system_output(grep, ignore_status=True):
        raise ValueError("Kernel doesn't have a %s feature" % (feature))


def cpu_online_map():
    """
    Check out the available cpu online map
    """
    cpus = []
    for line in open('/proc/cpuinfo', 'r').readlines():
        if line.startswith('processor'):
            cpus.append(line.split()[2]) # grab cpu number
    return cpus


def check_glibc_ver(ver):
    glibc_ver = commands.getoutput('ldd --version').splitlines()[0]
    glibc_ver = re.search(r'(\d+\.\d+(\.\d+)?)', glibc_ver).group()
    if utils.compare_versions(glibc_ver, ver) == -1:
        raise error.TestError("Glibc too old (%s). Glibc >= %s is needed." %
                              (glibc_ver, ver))

def check_kernel_ver(ver):
    kernel_ver = utils.system_output('uname -r')
    kv_tmp = re.split(r'[-]', kernel_ver)[0:3]
    # In compare_versions, if v1 < v2, return value == -1
    if utils.compare_versions(kv_tmp[0], ver) == -1:
        raise error.TestError("Kernel too old (%s). Kernel > %s is needed." %
                              (kernel_ver, ver))


def human_format(number):
    # Convert number to kilo / mega / giga format.
    if number < 1024:
        return "%d" % number
    kilo = float(number) / 1024.0
    if kilo < 1024:
        return "%.2fk" % kilo
    meg = kilo / 1024.0
    if meg < 1024:
        return "%.2fM" % meg
    gig = meg / 1024.0
    return "%.2fG" % gig


def numa_nodes():
    node_paths = glob.glob('/sys/devices/system/node/node*')
    nodes = [int(re.sub(r'.*node(\d+)', r'\1', x)) for x in node_paths]
    return (sorted(nodes))


def node_size():
    nodes = max(len(numa_nodes()), 1)
    return ((memtotal() * 1024) / nodes)


def to_seconds(time_string):
    """Converts a string in M+:SS.SS format to S+.SS"""
    elts = time_string.split(':')
    if len(elts) == 1:
        return time_string
    return str(int(elts[0]) * 60 + float(elts[1]))


def extract_all_time_results(results_string):
    """Extract user, system, and elapsed times into a list of tuples"""
    pattern = re.compile(r"(.*?)user (.*?)system (.*?)elapsed")
    results = []
    for result in pattern.findall(results_string):
        results.append(tuple([to_seconds(elt) for elt in result]))
    return results


def pickle_load(filename):
    return pickle.load(open(filename, 'r'))


# Return the kernel version and build timestamp.
def running_os_release():
    return os.uname()[2:4]


def running_os_ident():
    (version, timestamp) = running_os_release()
    return version + '::' + timestamp


def running_os_full_version():
    (version, timestamp) = running_os_release()
    return version


# much like find . -name 'pattern'
def locate(pattern, root=os.getcwd()):
    for path, dirs, files in os.walk(root):
        for f in files:
            if fnmatch.fnmatch(f, pattern):
                yield os.path.abspath(os.path.join(path, f))


def freespace(path):
    """Return the disk free space, in bytes"""
    s = os.statvfs(path)
    return s.f_bavail * s.f_bsize


def disk_block_size(path):
    """Return the disk block size, in bytes"""
    return os.statvfs(path).f_bsize


def get_cpu_family():
    procinfo = utils.system_output('cat /proc/cpuinfo')
    CPU_FAMILY_RE = re.compile(r'^cpu family\s+:\s+(\S+)', re.M)
    matches = CPU_FAMILY_RE.findall(procinfo)
    if matches:
        return int(matches[0])
    else:
        raise error.TestError('Could not get valid cpu family data')


def get_disks():
    df_output = utils.system_output('df')
    disk_re = re.compile(r'^(/dev/hd[a-z]+)3', re.M)
    return disk_re.findall(df_output)


def load_module(module_name):
    # Checks if a module has already been loaded
    if module_is_loaded(module_name):
        return False

    utils.system('/sbin/modprobe ' + module_name)
    return True


def unload_module(module_name):
    """
    Removes a module. Handles dependencies. If even then it's not possible
    to remove one of the modules, it will trhow an error.CmdError exception.

    @param module_name: Name of the module we want to remove.
    """
    l_raw = utils.system_output("/sbin/lsmod").splitlines()
    lsmod = [x for x in l_raw if x.split()[0] == module_name]
    if len(lsmod) > 0:
        line_parts = lsmod[0].split()
        if len(line_parts) == 4:
            submodules = line_parts[3].split(",")
            for submodule in submodules:
                unload_module(submodule)
        utils.system("/sbin/modprobe -r %s" % module_name)
        logging.info("Module %s unloaded" % module_name)
    else:
        logging.info("Module %s is already unloaded" % module_name)


def module_is_loaded(module_name):
    module_name = module_name.replace('-', '_')
    modules = utils.system_output('/sbin/lsmod').splitlines()
    for module in modules:
        if module.startswith(module_name) and module[len(module_name)] == ' ':
            return True
    return False


def get_loaded_modules():
    lsmod_output = utils.system_output('/sbin/lsmod').splitlines()[1:]
    return [line.split(None, 1)[0] for line in lsmod_output]


def get_huge_page_size():
    output = utils.system_output('grep Hugepagesize /proc/meminfo')
    return int(output.split()[1]) # Assumes units always in kB. :(


def get_num_huge_pages():
    raw_hugepages = utils.system_output('/sbin/sysctl vm.nr_hugepages')
    return int(raw_hugepages.split()[2])


def set_num_huge_pages(num):
    utils.system('/sbin/sysctl vm.nr_hugepages=%d' % num)


def get_cpu_vendor():
    cpuinfo = open('/proc/cpuinfo').read()
    vendors = re.findall(r'(?m)^vendor_id\s*:\s*(\S+)\s*$', cpuinfo)
    for i in xrange(1, len(vendors)):
        if vendors[i] != vendors[0]:
            raise error.TestError('multiple cpu vendors found: ' + str(vendors))
    return vendors[0]


def probe_cpus():
    """
    This routine returns a list of cpu devices found under
    /sys/devices/system/cpu.
    """
    cmd = 'find /sys/devices/system/cpu/ -maxdepth 1 -type d -name cpu*'
    return utils.system_output(cmd).splitlines()


def ping_default_gateway():
    """Ping the default gateway."""

    network = open('/etc/sysconfig/network')
    m = re.search('GATEWAY=(\S+)', network.read())

    if m:
        gw = m.group(1)
        cmd = 'ping %s -c 5 > /dev/null' % gw
        return utils.system(cmd, ignore_status=True)

    raise error.TestError('Unable to find default gateway')


def drop_caches():
    """Writes back all dirty pages to disk and clears all the caches."""
    utils.run("sync", verbose=False)
    # We ignore failures here as this will fail on 2.6.11 kernels.
    utils.run("echo 3 > /proc/sys/vm/drop_caches", ignore_status=True,
                 verbose=False)


def process_is_alive(name_pattern):
    """
    'pgrep name' misses all python processes and also long process names.
    'pgrep -f name' gets all shell commands with name in args.
    So look only for command whose initial pathname ends with name.
    Name itself is an egrep pattern, so it can use | etc for variations.
    """
    return utils.system("pgrep -f '^([^ /]*/)*(%s)([ ]|$)'" % name_pattern,
                        ignore_status=True) == 0


def get_hwclock_seconds(utc=True):
    """
    Return the hardware clock in seconds as a floating point value.
    Use Coordinated Universal Time if utc is True, local time otherwise.
    Raise a ValueError if unable to read the hardware clock.
    """
    cmd = '/sbin/hwclock --debug'
    if utc:
        cmd += ' --utc'
    hwclock_output = utils.system_output(cmd, ignore_status=True)
    match = re.search(r'= ([0-9]+) seconds since .+ (-?[0-9.]+) seconds$',
                      hwclock_output, re.DOTALL)
    if match:
        seconds = int(match.group(1)) + float(match.group(2))
        logging.debug('hwclock seconds = %f' % seconds)
        return seconds

    raise ValueError('Unable to read the hardware clock -- ' +
                     hwclock_output)


def set_wake_alarm(alarm_time):
    """
    Set the hardware RTC-based wake alarm to 'alarm_time'.
    """
    utils.write_one_line('/sys/class/rtc/rtc0/wakealarm', str(alarm_time))


def set_power_state(state):
    """
    Set the system power state to 'state'.
    """
    utils.write_one_line('/sys/power/state', state)


def standby():
    """
    Power-on suspend (S1)
    """
    set_power_state('standby')


def suspend_to_ram():
    """
    Suspend the system to RAM (S3)
    """
    set_power_state('mem')


def suspend_to_disk():
    """
    Suspend the system to disk (S4)
    """
    set_power_state('disk')