#!/usr/bin/env bash
echo
echo
echo "!!!!!!!!!!!!!!!!!!!!!!!!!!! provision_app.sh !!!!!!!!!!!!!!!!!!!!!!!!!!!"
echo
echo

apt-get update
apt-get install -y uwsgi apache2 postgresql-client
service apache2 stop
apt-get install -y python-psycopg2 python-gdal gdal-bin nginx locate python-virtualenv fabric uwsgi-plugin-python python-mapscript cgi-mapserver mapserver-bin mapcache-cgi mapcache-tools imagemagick python-lxml curl build-essential libssl-dev python-pip locales postgis
apt-get remove postgresql-10
a2enmod cgid
rm /etc/apache2/sites-enabled/* 2> /dev/null
rm /etc/nginx/sites-enabled/default 2> /dev/null
sed -i 's/^\(Listen\) 80$/\1 8080\n\1 7654/' /etc/apache2/ports.conf
sed -i 's/^# *\(es_AR.UTF-8\)/\1/' /etc/locale.gen
pip install simpleflock requests
/usr/sbin/locale-gen
export LC_ALL=es_AR.UTF-8; export LANGUAGE=es_AR.UTF-8; export LANG=es_AR.UTF-8
dpkg-reconfigure --frontend=noninteractive locales
getent passwd vagrant > /dev/null
if [ $? -eq 0 ]; then
    usermod -a -G www-data vagrant
fi
# update-locale LC_CTYPE=es_AR.UTF-8

