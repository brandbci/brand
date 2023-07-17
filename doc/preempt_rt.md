# Setup of PREEMPT_RT

## Installing the PREEMPT_RT Patch

### System Information (following PREEMPT_RT installation)

Example:
Kernel version (via `uname -msr`):
```bash
Linux 5.15.43-rt45 x86_64
```

Ubuntu version (via `lsb_release -a`):
```bash
Distributor ID:	Ubuntu
Description:	Ubuntu 20.04.3 LTS
Release:	    20.04
Codename:	    focal
```

### Downloading the patch

We recommend using the identical kernel version which was used to develop BRAND (`5.15.43-rt45`), which can be installed from the instructions below.

To download the kernel and patch, run the following (assumed from the user's home folder):
```
cd
mkdir -p Installs/rt-kernel
cd Installs/rt-kernel
wget https://mirrors.edge.kernel.org/pub/linux/kernel/v5.x/linux-5.15.43.tar.xz  # kernel
wget https://mirrors.edge.kernel.org/pub/linux/kernel/projects/rt/5.15/older/patch-5.15.43-rt45.patch.xz # patch
```

### Compiling and Installing the Kernel
Follow the steps below based on this [blog post](https://chenna.me/blog/2020/02/23/how-to-setup-preempt-rt-on-ubuntu-18-04/).

1. Install dependencies.
    ```
    sudo apt install build-essential git libssl-dev libelf-dev flex bison dwarves zstd libncurses-dev
    ```
1. Extract the archive and apply the patch.
    ```
    xz -cd linux-5.15.43.tar.xz | tar xvf -
    cd linux-5.15.43
    xzcat ../patch-5.15.43-rt45.patch.xz | patch -p1
    ```
1. Copy the old configuration as the basis for the new kernel.
    ```
    cp /boot/config-5.13.0-44-generic .config # example
    make menuconfig
    ```
1. Under `General setup --->` > `Preemption Model (Voluntary Kernel Preemption (Desktop)) --->` (or something in the parentheses) choose `Fully Preemptible Kernel (Real-Time)`. Hit `Exit` to go back to the top config menu.
1. Under `Cryptographic API (CRYPTO [-y])` > `Certificates for signature checking` (last item in the list) > `(debian/canonical-certs.pem) Additional X.509 keys for default system keyring` (or something like that in the parentheses), delete the string in the field.
1. In the same menu under `(debian/canonical-revoked-certs.pem) X.509 certificates to be preloaded into the system blacklist keyring` (or something like that in the parentheses), delete the string in the field.
1. Hit `Save`, then `Exit` all the way out of `menuconfig`.
1. Compile the new kernel. Note the `-j` option runs parallel jobs, so increase the number to speed up the process, but too many can hang the system. This step takes approximately 20 minutes to run on an Intel i9-12900.
    ```
    make -j8 all; sudo make -j8 modules_install; sudo make -j8 install
    ```
1. Update the `ramdisk` initialization options based on [this Stack Exchange post](https://unix.stackexchange.com/a/671382):
    ```
    sudo nano /etc/initramfs-tools/initramfs.conf
    ```
1. Update the `MODULES` line to say:
    ```
    MODULES=dep
    ```
1. Regenerate the `ramdisk` initialization options.
    ```
    sudo update-initramfs -c -k 5.15.43-rt45
    ```
1. Reboot to boot the `PREEMPT_RT` kernel.

#### Installation Notes

- After running the `dpkg -i` command, you may see warnings about missing firmware. Follow the instructions [here](https://askubuntu.com/questions/832524/possible-missing-frmware-lib-firmware-i915) to install that missing firmware.

### Newer Kernel Versions

BRAND was developed on, tested on, and officially supports kernel version `5.15.43-rt45`. Should you decide to use a new kernel version, we recommend following these instructions to locate a new kernel:
1. Find the most recent Linux long-term support kernel [here](https://kernel.org).
1. Go to the `PREEMPT_RT` project and find the most recent `rt` patch for the long-term support kernel version [here](https://mirrors.edge.kernel.org/pub/linux/kernel/projects/rt/).
1. Note that all three version numbers of the Linux kernel must match all three numbers of the `rt` patch (except the `rtXX`), so find the matching Linux kernel version [here](https://mirrors.edge.kernel.org/pub/linux/kernel/).
    - For example, If the most recent long-term Linux kernel version is `5.15.44` but the `rt` project only has `5.15.43`, then you must use the Linux kernel for version `5.15.43` too. Be sure to download the `.xz` file extension for the Linux kernel and the `.patch.xz` extension for the `rt` patch.
1. Complete the installation steps outlined above

### Testing the Kernel

#### Installing the tests

Dependencies:
```
sudo apt-get install libnuma-dev  # for cyclictest
```
Tests:
```
cd ~/Installs
git clone git://git.kernel.org/pub/scm/utils/rt-tests/rt-tests.git  # cyclictest
cd rt-tests/
git checkout stable/v1.0
make all
```

1. Open a second terminal instance and run:
    ```
    cd ~/Installs/rt-tests
    ```
1. Run a background process:
    ```
    ./hackbench -l10000000
    ```
1. Switch to the first terminal instance, and run:
    ```
    sudo ./cyclictest -l1000000 -m -Sp99 -i200 -h400 -q > output
    ```
    This will run for approximately three minutes.
1. When the above step is finished, switch back to the second terminal instance and kill the command with `CTRL+c`.

#### Generate the latency plot, based on [these instructions](http://www.osadl.org/Create-a-latency-plot-from-cyclictest-hi.bash-script-for-latency-plot.0.html).
1. Get maximum latency.
    ```
    max=`grep "Max Latencies" output | tr " " "\n" | sort -n | tail -1 | sed s/^0*//`
    ```
1. Grep data lines, remove empty lines and create a common field separator.
    ```
    grep -v -e "^#" -e "^$" output | tr " " "\t" >histogram 
    ```
1. Set the number of cores.
    ```
    cores=$(nproc)
    ```
1. Create two-column data sets with latency classes and frequency values for each core.
    ```
    for i in `seq 1 $cores`
    do
        column=`expr $i + 1`
        cut -f1,$column histogram >histogram$i
    done
    ```
1. Create plot command header.
    ```
    echo -n -e "set title \"Latency plot\"\n\
    set terminal png\n\
    set xlabel \"Latency (us), max $max us\"\n\
    set logscale y\n\
    set xrange [0:400]\n\
    set yrange [0.8:*]\n\
    set ylabel \"Number of latency samples\"\n\
    set output \"plot.png\"\n\
    plot " >plotcmd
    ```
1. Append plot command data references.
    ```
    for i in `seq 1 $cores`
    do
        if test $i != 1
        then
            echo -n ", " >>plotcmd
        fi
        cpuno=`expr $i - 1`
        if test $cpuno -lt 10
        then
            title=" CPU$cpuno"
        else
            title="CPU$cpuno"
        fi
        echo -n "\"histogram$i\" using 1:2 title \"$title\" with histeps" >>plotcmd
    done
    ```
1. Install and execute plot command.
    ```
    sudo apt-get install gnuplot -y
    gnuplot -persist <plotcmd
    ```
1. Switch to the GUI and open a new terminal. Then run:
    ```
    cd ~/Installs/rt-tests/
    firefox plot.png
    ```
    If `PREEMPT_RT` was properly installed, you should see a plot similar to the following, where most latency samples are crowded towards the left side near 0us latency. If `PREEMPT_RT` was not properly installed, you will likely see latency samples much more distributed on the horizontal axis.
    
    ![](preempt_rt_example_latency_plot.png)

#### Breaking down the [OSADL](http://www.osadl.org) `cyclictest` command (removed two zeros from -l100000000 for shorter runtime)
```
sudo ./cyclictest -l1000000 -m -Sp99 -i200 -h400 -q
```
```
-l1000000 = 1e6 loops
-m  = memlock
-S = use the standard testing options for SMP systems
-p99 = set the realtime priority to 99
-i200 = set base interval of the thread to 200 microseconds
-h400 = dump latency histogram to stdout. 400 microseconds is the max latency time to track.
-q = Run the tests quietly and print only a summary on exit.
```