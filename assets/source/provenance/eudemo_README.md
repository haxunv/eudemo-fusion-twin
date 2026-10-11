# EU-DEMO Reactor Design

To set up your bluemira environment run the following

```bash
bash scripts/install_bluemira.sh -i -t develop -p 3.12
```
If you have already have a conda installation you can remove `-i` and the conda step will be skipped. `-p` specifies the python version which defaults to 3.12

```bash
source ~/.miniforge-init.sh
conda activate bluemira-eudemo
```
## Running reactor designs

Studies can be run as shown for the first study once the setup has been completed:
```
python studies/first/reactor.py
```

## Neutronics

To run the neutronics analyses you will need to download the required neutronics cross section data into the folder studies/<study>/config/cross_section_data or modify the build_config.json accordingly. The neutronics source used is [tokamak-neutron-source](github.com/Fusion-Power-Plant-Framework/tokamak-neutron-source)
