# Instalación en Ubuntu 18.04
## Paquetes requeridos
Los paquetes requeridos se instalan al ejecutar el script provision.sh (automáticamente si se usa Vagrant, al ejecutar el primer vagrant up)

## Instalación usando vagrant
En el host instalar vagrant
```
sudo apt install vagrant
```
en la carpeta donde esté clonado el repo ejecutar:
```
vagrant up
```
y conectarse a la vm
```
vagrant ssh
```

##Activar entorno con nginx (simil prod http://localhost:8080)
Esta instalación tiene problemas con la aplicación de slds, el resto funciona bien, se recomienda usar una instalación con ip fija (o url) para solucionar el problema
```
$ cd /path/to/your/mapground (cd /vagrant)
$ sudo fab setup_prod
#To solve nginx permissions issues on /vagrant/MapGround set nginx user to vagrant
$ sudo vi /etc/nginx/nginx.conf
user vagrant 

$ sudo service nginx restart; sudo service apache2 restart; sudo service uwsgi restart
```

####test mapserver wms crudo (zona La Plata, cambiar .map y bbox a gusto):
http://localhost:8081/cgi-bin/mapserv?map=/var/local/mapground/mapfiles/[archivo.map]&SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&BBOX=-36.04719999999999658,-59.77500000000000568,-33.77850000000000108,-57.33739999999999668&CRS=epsg:4326&WIDTH=415&HEIGHT=566&LAYERS=default&STYLES=&FORMAT=image/png&DPI=96&MAP_RESOLUTION=96&FORMAT_OPTIONS=dpi:96&TRANSPARENT=TRUE

####test mapserver (cambiar .map a gusto, usa WMTS):
http://localhost:8080/cgi-bin/mapserv?map=/var/local/mapground/mapfiles/[archivo.map]&mode=browse&layers=all

####para testear con sld agregar a la url &SLD=http://localhost:8080/media/sld/[archivo.sld localizado en la carpeta /var/local/mapground/media/sld/]

###logs:
nginx: /var/log/nginx/
apache: /var/log/apache/
postgres: /var/log/postgresql/
tasks: /var/log/mapground/
mapserver: /var/local/mapground/mapfiles/map-error.log


##Activar entorno con nginx (simil prod ip fija o url)
Para fijar una ip usando vagrant descomentar en el Vagrantfile  la línea:
```
config.vm.network "private_network", ip: "192.168.33.10"
```
si hubiera conflicto buscar alguna sin conflicto en el rango de ip privada
si se necesitara mayor cantidad de memoria en la vm descomentar/modificar en el Vagrantfile las siguientes líneas
```
  config.vm.provider "virtualbox" do |vb|
    ...
    # Customize the amount of memory on the VM:
    vb.memory = "2048"
  end
```

El proceso de instalación es similar al anterior excepto que no puede usarse el fabfile

```
$ cd /path/to/your/mapground (cd /vagrant)
$ sudo ./setup.sh  -h="localhost" -s="http://192.168.33.10/"
#where -h -> db_host and -s -> site url (ip or server name)

#To solve nginx permissions issues on /vagrant/MapGround set nginx user to vagrant
$ sudo vi /etc/nginx/nginx.conf
user vagrant 

$ sudo service nginx restart; sudo service apache2 restart; sudo service uwsgi restart
```

####test mapserver wms crudo (zona La Plata, cambiar .map y bbox a gusto):
http://192.168.33.10:8080/cgi-bin/mapserv?map=/var/local/mapground/mapfiles/[archivo.map]&SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&BBOX=-36.04719999999999658,-59.77500000000000568,-33.77850000000000108,-57.33739999999999668&CRS=epsg:4326&WIDTH=415&HEIGHT=566&LAYERS=default&STYLES=&FORMAT=image/png&DPI=96&MAP_RESOLUTION=96&FORMAT_OPTIONS=dpi:96&TRANSPARENT=TRUE

####test mapserver (cambiar .map a gusto, usa WMTS): 
***revisar***
http://192.168.33.10:8080/cgi-bin/mapserv?map=/var/local/mapground/mapfiles/[archivo.map]&mode=browse&layers=all

####para testear con sld agregar a la url &SLD=http://localhost:8080/media/sld/[archivo.sld] localizado en la carpeta /var/local/mapground/media/sld/]

###logs:
nginx: /var/log/nginx/
apache: /var/log/apache/
postgres: /var/log/postgresql/
tasks: /var/log/mapground/
mapserver: /var/local/mapground/mapfiles/map-error.log


## Entorno de desarrollo  (http://localhost:8000)
La inicialización del entorno de desarrollo solo es necesario ejecutarla 1 vez y consiste en lo siguiente:
```
#!bash

$ cd /path/to/your/mapground (cd /vagrant)
# crear virtual environment la primera vez
$ virtualenv .
$ fab setup_dev
$ fab runserver
```
Usando una nueva terminal iniciar el demonio de tareas manualmente
```
$ cd /path/to/your/mapground (cd /vagrant)
$ ./run_tasks.sh

```
###logs:
apache: /var/log/apache/
postgres: /var/log/postgresql/
tasks: /var/log/mapground/
mapserver: /var/local/mapground_dev/mapfiles/map-error.log


## Deploy en entorno productivo
El deploy en producción, una vez corrido el provision.sh, consiste en lo siguiente:
```
#!bash

$ cd /path/to/your/mapground
$ fab setup_prod
```
Para alternar entre ambos entornos se usan los comandos (no funciona del todo bien, revisar!!!):
```
#!bash

$ cd /path/to/your/mapground
$ fab dev # para pasar a dev
$ fab prod # para pasar a prod
```
