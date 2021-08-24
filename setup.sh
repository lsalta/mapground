#!/usr/bin/env bash

# Nos aseguramos de que el script se corra como root
if [ "$(id -u)" != "0" ]; then
   echo "Este script debe correrse root" 1>&2
   exit 1
fi

export LC_ALL='es_AR.UTF-8'
export LANGUAGE='es_AR.UTF-8'
export LANG='es_AR.UTF-8'

LOG_DIR='/var/log/mapground'

for i in "$@"
do
case $i in
    -f=*|--files=*)
    files="${i#*=}"
    ;;
    -c=*|--cache=*)
    cache="${i#*=}"
    ;;
    -h=*|--dbhost=*)
    dbhost="${i#*=}"
    ;;
    -d=*|--dbname=*)
    dbname="${i#*=}"
    ;;
    -u=*|--dbuser=*)
    dbuser="${i#*=}"
    ;;
    -p=*|--dbpass=*)
    dbpass="${i#*=}"
    ;;
    -s=*|--siteurl=*)
    siteurl="${i#*=}"
    ;;
    -l=*|--cluster=*)
    cluster="${i#*=}"
    ;;
    *)
            # unknown option
    ;;
esac
done

if [ -z "$files" ]; then 
FILES_DIR='/var/local/mapground';
else 
FILES_DIR=$files;
fi
echo "Using '${FILES_DIR}' for storing app files..."

if [ -z "$cache" ]; then
CACHE_DIR='/var/cache/mapground';
else 
CACHE_DIR=$cache; 
fi
echo "Using '${CACHE_DIR}' for storing tiles cache..."

if [ -z "$siteurl" ]; then
SITE_URL='http://localhost:8080/';
else 
SITE_URL=$siteurl; 
fi
echo "Using '${SITE_URL}' for SITE_URL..."

if [ -z "$cluster" ]; then cluster_param=''; else cluster_param="-c=${cluster}"; echo "Directorio para cluster DB: $cluster"; fi

if [ -z "$dbname" ]; then dbname='mapground'; echo "Base de datos por defecto: $dbname"; fi
if [ -z "$dbuser" ]; then dbuser='mapground'; echo "Usuario de base de datos por defecto: $dbuser"; fi

if [ -z "$dbhost" ]; then
   echo "Uso: setup.sh -h=<database host> [[-d=<database name>] [-u=<database user>] [-p=<database pass>] [-s=<site url>] [-f=<files directory>] [-c=<tiles cache directory>] [-l=<cluster DB directory>]]" 1>&2
   exit 1
fi


if [ "$dbhost" = "localhost" ]; then
  echo "Configurando base de datos en localhost...";
  
  if [ -z "$dbpass" ]; then
    read -s -p "Ingrese el password para asignar al usuario de la base de datos:" dbpass;
    echo;
  fi

  ./setup_db.sh -d=$dbname -u=$dbuser -p=$dbpass ${cluster_param};
fi

if [ -z "$dbpass" ]; then
  read -s -p "Ingrese el password asignado al usuario de la base de datos:" dbpass;
  echo;
fi

SECRET_KEY=$(python mk_secret_key.py)

DIR="$( cd "$(dirname "$0")" ; pwd -P )"

DEV_USER="$(ls -ld $0 | awk '{print $3}')"

sed -e "s/mapground-db/${dbname}/g" MapGround/settings_db.py.template | sed -e "s/mapground-user/${dbname}/g" - | sed -e "s/mapground-password/${dbpass}/g" - | sed -e "s/mapground-host/${dbhost}/g" - | sed -e "s/secret-key/${SECRET_KEY}/g" > MapGround/settings_local_db.py
sed -e "s/\DEBUG = True$/DEBUG = False/" MapGround/settings_local.py.template > MapGround/settings_local.py
sed -i "s:/var/local/mapground:${FILES_DIR}:g" MapGround/settings_local.py
sed -i "s:/var/cache/mapground:${CACHE_DIR}:g" MapGround/settings_local.py
sed -i "s|SITE_URL = 'http://localhost:8080/'|SITE_URL = '${SITE_URL}'|g" MapGround/settings_local.py

sed -e "s:/path/to/your/mapground:${DIR}:g" mapground_uwsgi.ini.template > mapground_uwsgi.ini
chown $DEV_USER MapGround/settings_local_db.py MapGround/settings_local.py mapground_uwsgi.ini

rm -rf ${CACHE_DIR} 2>/dev/null
rm -rf ${FILES_DIR} 2>/dev/null
rm -rf ${LOG_DIR} 2>/dev/null

mkdir ${CACHE_DIR}
mkdir ${FILES_DIR}
mkdir ${LOG_DIR}
mkdir ${FILES_DIR}/media
cp -r mapfiles ${FILES_DIR}
touch ${FILES_DIR}/mapfiles/map-error.log
chmod 666 ${FILES_DIR}/mapfiles/map-error.log
cp -r data ${FILES_DIR}
# chown -R ${USER:=$(/usr/bin/id -run)}:$USER ${FILES_DIR}
cp mapcache/mapcache.xml.template ${FILES_DIR}/mapcache.xml

cp mapground_uwsgi.ini /etc/uwsgi/apps-available/mapground.ini
rm /etc/uwsgi/apps-enabled/mapground.ini 2>/dev/null
ln -s /etc/uwsgi/apps-available/mapground.ini /etc/uwsgi/apps-enabled/mapground.ini
sed -e "s:/path/to/your/mapground:${DIR}:g" mapground_nginx+apache.conf.template > /etc/nginx/sites-available/mapground
sed -i "s:/var/local/mapground:${FILES_DIR}:g" /etc/nginx/sites-available/mapground
rm /etc/nginx/sites-enabled/mapground 2>/dev/null
ln -s /etc/nginx/sites-available/mapground /etc/nginx/sites-enabled/mapground
sed -e "s:/var/local/mapground:${FILES_DIR}:g" mapground_apache.conf.template > /etc/apache2/sites-available/mapground.conf
# cp mapground_apache.conf.template /etc/apache2/sites-available/mapground.conf
rm /etc/apache2/sites-enabled/mapground.conf 2>/dev/null
ln -s /etc/apache2/sites-available/mapground.conf /etc/apache2/sites-enabled/mapground.conf

sudo -u ${DEV_USER} bash -c 'virtualenv -p python2.7 --system-site-packages venv; source venv/bin/activate; pip install -r requirements.txt'

source venv/bin/activate

echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! migrations !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
python manage.py makemigrations
echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! migrate !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
python manage.py migrate
echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! fixtures !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
python manage.py loaddata MapGround/fixtures/user.json
python manage.py loaddata layers/fixtures/initial_data.json
python manage.py loaddata maps/fixtures/initial_data.json
python manage.py collectstatic --noinput
python manage.py add_tileset world_borders

deactivate

chown -R www-data:www-data ${FILES_DIR} ${CACHE_DIR}
chown ${DEV_USER} ${FILES_DIR}/mapcache.xml

service uwsgi restart
service apache2 restart
service nginx restart