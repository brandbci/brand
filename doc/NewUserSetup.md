# How to add a new user for BRAND use

## Create a new user

You can create a new user either locally or over SSH. Note that SSH may not be enabled on a new computer.

First, via a user with sudo permissions, add a new user, and fill in the prompts as desired (leaving all fields empty is fine):
```
sudo adduser <new_user>
```

This user will need sudo permissions later, so before logging into the user, give it sudo permissions.
```
sudo usermod -aG sudo <new_user>
```

Now, log out of the current user and log into the new user.

## Set up conda

### Install conda

Next, you have to recreate the conda environment. To do so, create an `Installs` directory:
```
mkdir Installs
```
And also create a new folder to store miniconda and other installed software:
```
mkdir lib
```

Then, download the latest [miniconda installer](https://docs.conda.io/projects/conda/en/latest/user-guide/install/linux.html) to `Installs`. Download the newest version for Python 3.8, or whatever is the current version of Python being used for BRAND. As of September 2022, the latest version can be downloaded with the following command:
```
cd Installs
wget https://repo.anaconda.com/miniconda/Miniconda3-py38_4.12.0-Linux-x86_64.sh
```

Now install miniconda:
```
bash Miniconda3-<latest>-Linux-x86_64.sh
```
When prompted, set the install directory to be `/home/<new_user>/lib/miniconda3`.

If prompted about whether to initialize miniconda, enter `yes`.

*NOTE that the following conda-related steps do not need to be run if you intend to install BRAND. If so, skip to the [Installing BRAND](#installing-brand) section below.*

### Recreating an environment from a pre-existing one

When creating a new user, one may want to build an identical conda environment and its packages to a pre-existing one from a different user. To do so, first log into the user account containing the original conda environment and activate the environment.
```
conda activate <env>
conda env export > <env>_env.yml
```

Switch back to the `new_user` account, create a new environment, copy the `<env>_env.yml` file to `/home/<new_user>/Installs`, then install it.
```
cd
cp /path/to/<env>_env.yml /home/<new_user>/Installs
conda env create -f Installs/<env>_env.yml
```

### Installing missing packages

Exporting a conda environment only exports packages that can be installed by `pip`. Packages that cannot be installed by pip need to be installed manually.

## Set up SSH key for Git login (optional)

These steps are required if you want to setup Git login with an SSH key instead of through HTTPS. Instructions adapted from GitHub docs: [[1]](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent) and [[2]](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/adding-a-new-ssh-key-to-your-github-account).

Generate a new SSH key, replacing the below with your GitHub email:
```
ssh-keygen -t ed25519 -C "<your_email>@<example.com>"
```
When prompted to "Enter a file in which to save the key," press Enter. This accepts the default file location.

Then, when prompted, enter a passphrase. Can be left empty for no passphrase. The key will be created after this.

Now, start the ssh-agent in the background.
```
eval "$(ssh-agent -s)"
```
And add your new SSH private key to the ssh-agent.
```
ssh-add ~/.ssh/id_ed25519
```

Now, to add this new SSH key to your GitHub account:
1. Login to Github through a web browser
2. On the upper-right corner of the page, click on your profile picture and then *Settings* on the drop-down menu. 
3. Click on *Access>SSH and GPC keys* from the left sidebar.
4. Click on *New SSH key*.
5. Give a title to your new SSH key (e.g. snel-devX-brand)
6. Within a terminal on your new BRAND machine, run the following command to print the contents of your SSH key, and copy the output to the clipboard (should being with `ssh-ed25519`):
   ```
   cat ~/.ssh/id_ed25519.pub
   ```
7. Back on the web browser, paste the contents of your SSH key to the *Key* field.
8. Click *Add SSH key*. You may be prompted to confirm with your GitHub credentials.

# Installing BRAND

Create a projects directory into which we will store BRAND, then clone the `dev` branch (current stable branch) from the repository [repository](https://github.com/snel-repo/realtime_rig_dev/tree/dev). 
```
cd
mkdir Projects
cd Projects
```
If you want to clone the repo using HTTPS, run the following:
```
git clone -b dev https://github.com/snel-repo/realtime_rig_dev.git
```
If you prefer to clone using SSH, run the following (you must have setup an SSH key for this purpose following the previous optional steps):
```
git clone -b dev git@github.com:snel-repo/realtime_rig_dev.git
```

Now build BRAND by following the instructions in `Projects/realtime_rig_dev/README.md`, providing the password as needed.
