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
    -d=*|--dbname=*)
    dbname="${i#*=}"
    ;;
    -u=*|--dbuser=*)
    dbuser="${i#*=}"
    ;;
    -p=*|--dbpass=*)
    dbpass="${i#*=}"
    ;;
    *)
            # unknown option
    ;;
esac
done

if [ -z "$files" ]; then 
FILES_DIR='/var/local/mapground_dev';
else 
FILES_DIR=$files;
fi
echo "Using '${FILES_DIR}' for storing app files..."

if [ -z "$cache" ]; then
CACHE_DIR='/var/cache/mapground_dev';
else 
CACHE_DIR=$cache; 
fi
echo "Using '${CACHE_DIR}' for storing tiles cache..."

if [ -z "$dbname" ]; then dbname='mapground_dev'; echo "Base de datos por defecto: $dbname"; fi
if [ -z "$dbuser" ]; then dbuser='mapground_dev'; echo "Usuario de base de datos por defecto: $dbuser"; fi
if [ -z "$dbhost" ]; then dbhost='localhost'; fi

echo "Configurando base de datos en localhost...";

if [ -z "$dbpass" ]; then
  read -s -p "Ingrese el password para asignar al usuario de la base de datos:" dbpass;
  echo;
fi

./setup_db.sh -d=$dbname -u=$dbuser -p=$dbpass ;

SECRET_KEY=$(python mk_secret_key.py)

DIR="$( cd "$(dirname "$0")" ; pwd -P )"

DEV_USER="$(ls -ld $0 | awk '{print $3}')"

sed -e "s/mapground-db/${dbname}/g" MapGround/settings_db.py.template | sed -e "s/mapground-user/${dbname}/g" - | sed -e "s/mapground-password/${dbpass}/g" - | sed -e "s/mapground-host/${dbhost}/g" | sed -e "s/secret-key/${SECRET_KEY}/g" > MapGround/settings_dev_db.py
sed -e "s:/var/local/mapground_dev:${FILES_DIR}:g" MapGround/settings_local.py.template > MapGround/settings_local.py
sed -i "s:/var/cache/mapground_dev:${CACHE_DIR}:g" MapGround/settings_local.py
# cp MapGround/settings_local.py.template MapGround/settings_local.py
chown $DEV_USER MapGround/settings_dev_db.py MapGround/settings_local.py

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
chown -R $DEV_USER ${FILES_DIR}
cp mapcache/mapcache.xml.template ${FILES_DIR}/mapcache.xml

sed -e "s:/var/local/mapground:${FILES_DIR}:g" mapground_apache.conf.template > /etc/apache2/sites-available/mapground_dev.conf
sed -i "s/^<VirtualHost \*:8080>$/<VirtualHost *:7654>/" /etc/apache2/sites-available/mapground_dev.conf
rm /etc/apache2/sites-enabled/mapground_dev.conf 2>/dev/null
ln -s /etc/apache2/sites-available/mapground_dev.conf /etc/apache2/sites-enabled/mapground_dev.conf

./setup_tasks.sh

sudo -u ${DEV_USER} bash -c 'virtualenv --system-site-packages venv; source venv/bin/activate; pip install -r requirements.txt'

source venv/bin/activate

python manage.py makemigrations
python manage.py migrate
python manage.py loaddata MapGround/fixtures/user.json
python manage.py loaddata layers/fixtures/initial_data.json
python manage.py loaddata maps/fixtures/initial_data.json
python manage.py add_tileset world_borders

deactivate

chown -R www-data:www-data ${CACHE_DIR}
chmod g+rwxs ${CACHE_DIR}
chmod 666 ${FILES_DIR}/mapcache.xml

service apache2 restart
