# HTTP Proxy
### HTTP proxy with management capability

A final project for the Gvahim program. This project provides proxy server,
with management capabilities for HTTP requests. When the server is running, all
network between the browser and the internet goes through the proxy, allowing
it to store and use cache, and display statistics.


## Getting Started
These instructions will get you a copy of the project up and running on your
local machine for development and testing purposes.

### Prerequisites
Here are the things you will need to download in order to get this system up
and running:

```
1) Download and install Python2.7 (https://www.python.org/download/releases/2.7/)
2) Download this repository on your machine (Posix machine only)
3) On Windows, download and install Cygwin
4) Download and install any modern browser
5) Set up your browser to use proxy, according to the ip where the program will run and the port you'll choose (on Firefox, use "Foxyproxy")
```
### Execution

Reach parent directory (HTTP-proxy)
```
cd [location of HTTP-proxy]
```
Running the Proxy:
```
python -m proxy [args]
```

### Arguments
All arguments are optional. To view defaults, see --help.
Execution with arguments would look like:
```
python -m proxy --proxy-bind-port 8080 --server-bind-port 9090 --log-file log --log-level DEBUG
```

### Graphical Interface

There is no graphical interface as part of the main program.
In order to enter the GUI in your browser type:
```
(your_ip):9090/manage
```
This will open the main page where statistics about the program and cache details may be seen.

## Authors

* **Ofer Bear** - *Initial work* - [My Profile](https://github.com/oferbear)

## Acknowledgments

* Thanks to Alon Bar-Lev and Sarit Lulav for teaching, helping and commenting.
