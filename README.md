<!---
Visit [Writing READMEs for Research Code & Software](https://data.research.cornell.edu/data-management/sharing/writing-readmes-for-research-code-software/) guidance for more details

-->


# GENERAL INFORMATION

**CNS-OpenIrisDAC:** This project is a fork of (OpenIrisDAC)[https://github.com/ryan-ressmeyer/OpenIrisDAC]. It is modified to work in the environment of the (Usrey Lab)[https://usreyneuroscience.ucdavis.edu/] at the UC Davis Center for Neuroscience ((CNS))[https://neuroscience.ucdavis.edu/].

**Version:** As of Aug,2026, we are still under development. The **main** branch is where all the action is.

**Short description:** This application is an analog output client for the (Dual Purkinje Image eye tracker)[https://github.com/ryan-ressmeyer/OpenIrisDPI] developed by Ryan Ressmeyer. Check the project out, along with the (wiki)[https://github.com/ryan-ressmeyer/OpenIrisDPI/wiki], a terrific resource. Our tracker hardware differs from the wiki model in some respects, but the core of the system (camera, IR source, OpenIrisDPI software) is identical to the wiki design.


# PROJECT OVERVIEW

**Full description:** This program acts as a client to the streaming tracking data from the OpenIrisDPI control program. It provides analog output for the tracker's measured x- and y-positions via a DAC, which can be used by a data acquisition process to monitor eye position in an experiment. 

**Project Organization:** This project is a fork of (OpenIrisDAC)[https://github.com/ryan-ressmeyer/OpenIrisDAC].

___

# INSTALLATION

**Step by step instructions:** 

1. Fetch github repo to a computer.
2. Set up a virtual env using your preferred method. Development was done using python 3.12, and I recommend that version.
3. Prepare virtual env.
```shell
$ pip install -r requirements.txt
``` 

**System requirements:** 

This application will only run on Windows.

[!Note]: If using the (AccesIO USB-AO16-8E)[https://accesio.com/usb-data-acquisition-daq-products/#cat-analog-output-usb], the drivers must be installed. A different DAC can be used, but it will require a dac module (see dac.py and nodac.py). 

**Required libraries, packages, modules:** Provide a list of required dependencies (e.g., libraries, packages, modules, etc.) [!Tip] * A package management tool can generate a list of dependencies for a project (e.g., Python’s pip freeze will output a list of installed packages in a format that can be used to create a “requirements.txt” file)

**Setup requirements:** Provide a description of any setup requirements (e.g., environment variables, configuration files)

**Known issues:** Provide any known issues or caveats during installation. (e.g., compatibility issues or known bugs)

___

# USAGE
 
**Step by step instructions:** Provide instructions on how run the software or execute the code after all of the required software project has been installed and include a brief description of what the expected output or behaviour should be
- Provide usage examples
- Include screenshots where appropriate
- Document how to run any built-in tests
**Known limitations:** Note any known caveats or limitations

___

# LICENSE

**Software License:** Provide a license (e.g., MIT) and LICENSE file and/or explain any restrictions on use
[!Note] This should also be in the source code as well
Visit https://choosealicense.com for useful and short summaries on the licenses
**Preferred citation:** Provide a citation that users can reference in publications

___

# CONTACT INFORMATION
[!Note] Provide at least two contacts; repeat block for additional contributors as needed

**Contact**
Name:
Role: (e.g., principal investigator, programmer, developer, maintainer, copyright owner)
ORCID:
Institution:
Email:

**Contact**
Name:
Role: (e.g., principal investigator, programmer, developer, maintainer, copyright owner)
ORCID:
Institution:
Email:

___

# ACKNOWLEDGEMENTS

**Funding:** Provide a list of funding sources that supported the creation of the software project; include funder name and grant number(s)
**Publications using our software:** Add citations to any publications using this software project
**Project is available:** Add a link to other locations where the software project is available (e.g., Zenodo, GitHub, institutional repository)
**Related relationships:** List relationships to ancillary scripts, applications, or data sets
**Contributors:** List all contributors and their roles
