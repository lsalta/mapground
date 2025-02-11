# -*- coding: utf-8 -*-
# from __future__ import unicode_literals   # NO DESCOMENTAR! ROMPE TODO!

from django.db import models, connection, connections
from django.contrib.auth.models import User
from django.conf import settings
# import mapscript
from layerimport.models import TablaGeografica, ArchivoRaster
from layers.models import Capa, Categoria, Metadatos, Atributo, ArchivoSLD, Escala
from layers.models import RasterDataSource, VectorDataSource, CONST_VECTOR, CONST_RASTER
import os
# slugs
from django.utils.text import slugify
# signals
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.contrib.gis.geos import MultiPoint
# fts
from djorm_pgfulltext.models import SearchManager
from djorm_pgfulltext.fields import VectorField
# misc
from utils.commons import normalizar_texto, urlToFile, coordConvert, take
import urlparse
import urllib
import urllib2
import time
from lxml import etree
from subprocess import call
from utils import mapserver
from mapcache import mapcache
from .tasks import add_tileset, rm_tileset, add_or_replace_tileset
import json
from sequences.models import Sequence
from utils.db import drop_table
import pytz

MAPA_DEFAULT_SRS = 3857
MAPA_DEFAULT_SIZE = (110, 150)
MAPA_DEFAULT_IMAGECOLOR = '#C6E2F2' # debe ser formato Hexa

TIPO_DE_MAPA_ENUM = (
    ('', ''),
    ('layer', 'layer'), # mapa de capa
    ('layer_original_srs', 'layer_original_srs'), # mapa de capa con srs original
    ('user', 'user'), # mapa de usuario
    ('public_layers', 'public_layers'), # mapa de todas las capas publicas en el sistema
    ('general', 'general'), # mapa de cualquier otro mapa creado ad-hoc
    ('layer_raster_band', 'layer_raster_band') # mapa subproducto de alguna banda raster
)

def RepresentsPositiveInt(s):
    try: 
        i = int(s)
        return i > 0
    except ValueError:
        return False

class TMSBaseLayer(models.Model):
    nombre = models.CharField('Nombre', null=False, blank=False, unique=True, max_length=255)
    url = models.CharField('URL', null=False, blank=False, max_length=2000)
    min_zoom = models.IntegerField('Min zoom', null=True, blank=True)
    max_zoom = models.IntegerField('Max zoom', null=True, blank=True)
    tms = models.BooleanField(u'TMS?', null=False, default=True)
    fuente = models.CharField('Fuente', null=False, blank=True, max_length=255) # attribution
    descripcion = models.TextField(u'Descripción', null=False, blank=True, max_length=10000)

    class Meta:
        verbose_name = 'TMS Base Layer'
        verbose_name_plural = 'TMS Base Layers'
    def __unicode__(self):
        return unicode(self.nombre)


class ManejadorDeMapas:
    @classmethod
    def delete_mapfile(cls, id_mapa):
        print "...ManejadorDeMapas.delete_mapfile %s"%(id_mapa)
        try:
             mapa=Mapa.objects.get(id_mapa=id_mapa)
        # if instance.tipo_de_mapa == 'layer':
        #     manage.remove([instance.id_mapa])
        except:
            print "......error: mapa inexistente"
            return
        try:
            os.remove(os.path.join(settings.MAPAS_PATH, id_mapa+'.map'))
        except:
            pass
#         #if mapa.tipo_de_mapa in ['layer_original_srs', 'general']:
#         try:
#             os.remove(os.path.join(settings.MEDIA_ROOT, id_mapa+'.png'))
#         except:
#             pass    
        

    @classmethod
    def commit_mapfile(cls,id_mapa):
        print "ManejadorDeMapas.commit_mapfile: %s" %(id_mapa)
        mapfile_full_path=os.path.join(settings.MAPAS_PATH, id_mapa+'.map')
        if not os.path.isfile(mapfile_full_path):
            if id_mapa=='mapground_public_layers':
                cls.regenerar_mapa_publico()
            else:
                try:
                    mapa=Mapa.objects.get(id_mapa=id_mapa)
                except:
                    print "....ManejadorDeMapas.commit_mapfile: ERROR: mapa inexistente %s" %(mapfile_full_path) 
                    return ''
                if mapa.tipo_de_mapa=='user':
                    cls.regenerar_mapas_de_usuarios([mapa.owner])
                elif mapa.tipo_de_mapa=='public_layers':
                    cls.regenerar_mapa_publico()
                elif mapa.tipo_de_mapa=='layer_raster_band':
                    mapa.save() 
                elif mapa.tipo_de_mapa in ['layer', 'layer_original_srs']:
                    mapa.save() 
                elif mapa.tipo_de_mapa in ['general']: # a evaluar...
                    mapa.save()
                else:
                    return ''
        return mapfile_full_path
    
    @classmethod
    def regenerar_mapas_de_usuarios(cls,lista_users_inicial=None):
        from users.models import ManejadorDePermisos
        print "...ManejadorDeMapas.regenerar_mapas_de_usuarios %s"%(str(lista_users_inicial))
        q = Mapa.objects.filter(tipo_de_mapa='user')
        if lista_users_inicial is not None:
            q = q.filter(owner__in=lista_users_inicial)
        for m in q:
            m.mapserverlayer_set.all().delete()
            lista_capas=ManejadorDePermisos.capas_de_usuario(m.owner, 'all').order_by('metadatos__titulo')
            for idx, c in enumerate(lista_capas):
                MapServerLayer(mapa=m,capa=c,orden_de_capa=idx).save()
            m.save()
    
    @classmethod
    def regenerar_mapa_publico(cls):
        print "...ManejadorDeMapas.regenerar_mapa_publico"
        m, created = Mapa.objects.get_or_create(owner=User.objects.get(username='mapground'),nombre='mapground_public_layers',id_mapa='mapground_public_layers', tipo_de_mapa='public_layers')
        m.mapserverlayer_set.all().delete()
        for idx, c in enumerate(Capa.objects.filter(wxs_publico=True)):
            MapServerLayer(mapa=m,capa=c,orden_de_capa=idx).save()
        m.save()

    @classmethod
    def generar_thumbnail(cls,id_mapa):
        print "...ManejadorDeMapas.generar_thumbnail"
        try:
            mapa=Mapa.objects.get(id_mapa=id_mapa)
            thumb = mapa.generar_thumbnail()
            return thumb
        except:
            return ''
        
    @classmethod
    def generar_legend(cls,id_mapa):
        print "...ManejadorDeMapas.generar_legend"
        try:
            mapa=Mapa.objects.get(id_mapa=id_mapa)
            return mapa.generar_legend()
        except:
            return False

    @classmethod
    def existe_mapa(cls, id_mapa):
        try:
            mapa=Mapa.objects.get(id_mapa=id_mapa)
            return True
        except:
            return False

# podria ser Mapa/MapServerMap por separado
class Mapa(models.Model):
    owner = models.ForeignKey(User, null=False,blank=False) 
    nombre = models.CharField('Nombre', null=False, blank=False, max_length=255)
    id_mapa = models.CharField('Id mapa', null=False, blank=False, unique=True, max_length=255)
    slug = models.SlugField('Slug', null=False, blank=True, max_length=255)
    
    # metadatos del mapa
    titulo = models.CharField(u'Título', null=False, blank=True, max_length=255) # title
    fuente = models.TextField(u'Fuente', null=False, blank=True, max_length=1000) # attribution
    contacto = models.TextField(u'Contacto', null=False, blank=True, max_length=1000) # contact organization
    descripcion = models.TextField(u'Descripción', null=False, blank=True, max_length=10000) # abstract
    #fechas?
    
    srs = models.CharField('SRS', null=False, blank=True, max_length=255)
    tipo_de_mapa = models.CharField('Tipo de Mapa', choices=TIPO_DE_MAPA_ENUM, max_length=30, null=False, blank=True, default='')   

    tms_base_layer = models.ForeignKey(TMSBaseLayer, verbose_name='Capa Base', null=True, blank=True, on_delete=models.SET_NULL)    
    capas = models.ManyToManyField(Capa, blank=True, through='MapServerLayer') 
    
    size = models.CharField('Size', null=False, blank=True, max_length=100)
    extent = models.CharField('Extent', null=False, blank=True, max_length=100)
    imagecolor = models.CharField('Imagecolor', null=False, blank=True, max_length=100)
    imagetype = models.CharField('Imagetype', null=False, blank=True, max_length=100) #TODO
    # seguir agregando tags de mapserver

    publico = models.BooleanField(u'Público?', null=False, default=False)
    categorias = models.ManyToManyField(Categoria, blank=True, verbose_name=u'Categorías')
    escala = models.ForeignKey(Escala, null=True, blank=True, on_delete=models.SET_NULL)
    palabras_claves = models.TextField(u'Palabras Claves', null=False, blank=True, max_length=10000,default='')
    
    texto_output = models.TextField(u'Texto Output', null=False, blank=True, max_length=10000)
    
    timestamp_alta = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de alta')
    timestamp_modificacion = models.DateTimeField(auto_now=True, verbose_name='Fecha de última modificación')

    input_search_index = models.TextField(null=False, blank=True, default='')
    search_index = VectorField()

    class Meta:
        verbose_name = 'Mapa'
        verbose_name_plural = 'Mapas'
    def __unicode__(self):
        return unicode(self.nombre)

    def actualizar_input_search_index(self):
        if self.tipo_de_mapa=='general':
            textos = []
            textos.append(normalizar_texto(self.titulo))
            textos.append(normalizar_texto(self.palabras_claves))
            textos.append(normalizar_texto(self.escala))
            textos.append(normalizar_texto(self.descripcion))
            self.input_search_index = ' '.join(textos)
    
    def save(self, *args, **kwargs):
        escribir_imagen_y_mapfile = kwargs.pop('escribir_imagen_y_mapfile', True)
        self.slug=slugify(unicode(self.nombre)).replace('-', '_')
        
        # esto es para los casos de mapas 'general' que se crean a partir del titulo del form
        # los otros casos se completan en los creates de los objetos
        if self.nombre == '':
            self.nombre=unicode(normalizar_texto(self.titulo))
        if self.id_mapa == '':
            self.id_mapa = '%s_%s'%(self.owner.username,self.nombre)

        try:
            msm=self.create_mapfile(False)
            self.texto_output=msm.convertToString()[0:9999]
        except:
            self.texto_output=''
        if self.tipo_de_mapa=='general':
            self.actualizar_input_search_index()
        super(Mapa, self).save(*args, **kwargs)
        if escribir_imagen_y_mapfile:
            self.create_mapfile(True)
            self.generar_thumbnail_y_legend()
            if self.tipo_de_mapa in ('layer', 'general'):# , 'layer_raster_band'):
                self.agregar_a_mapcache()
        return True

    @property
    def dame_titulo(self):
        if self.titulo != '':
            return self.titulo
        if self.tipo_de_mapa in ('layer_original_srs', 'layer'):
            try:
                return self.capas.first().dame_titulo
            except:
                pass
        elif self.tipo_de_mapa in ('layer_raster_band'):
            try:
                try:
                    msl = self.mapserverlayer_set.first()
                    banda = ' - ' + msl.capa.gdal_metadata['variables_detectadas'][msl.banda]['elemento']
                except:
                    banda = ''
                return self.capas.first().dame_titulo + banda
            except:
                pass

        return ''

    @property
    def dame_descripcion(self):
        if self.descripcion != '':
            return self.descripcion
        if self.tipo_de_mapa in ('layer_original_srs', 'layer'):
            try:
                return self.capas.first().dame_descripcion
            except:
                pass
        return ''
    @property
    def dame_fuente(self):
        if self.fuente!='':
            return self.fuente
        if self.tipo_de_mapa in ('layer_original_srs', 'layer'):
            try:
                return self.capas.first().dame_fuente
            except:
                pass
        return ''
    @property
    def dame_contacto(self):
        if self.contacto!='':
            return self.contacto
        if self.tipo_de_mapa in ('layer_original_srs', 'layer'):
            try:
                return self.capas.first().dame_contacto
            except:
                pass
        return ''
    @property
    def dame_tilesurl(self):
        if self.tipo_de_mapa in ('layer_original_srs', 'layer'):
            try:
                c = self.capas.first()
                return settings.MAPCACHE_URL+'tms/1.0.0/%s@GoogleMapsCompatible/{z}/{x}/{y}.png?t=%s'%(c.id_capa, time.mktime(c.timestamp_modificacion.timetuple()))
            except:
                pass
        elif self.tipo_de_mapa in ('general', 'layer_raster_band'):
            return settings.MAPCACHE_URL+'tms/1.0.0/%s@GoogleMapsCompatible/{z}/{x}/{y}.png?t=%s'%(self.id_mapa, time.mktime(self.timestamp_modificacion.timetuple()))
        return ''
    # devuelve un string parametrizable tipo '-71.55 -41.966667 -63.0 -37.9'
    def dame_extent(self, separator=' ', srid=4326):
        # TODO: creo que en el caso de layer_raster_band habria que sacar el extent de los metadatos de la banda, ya que *quizas* cada uno podria tener uno distinto
        if self.tipo_de_mapa in ('layer_original_srs', 'layer', 'layer_raster_band'):
            try:
                c = self.capas.first()
                return c.dame_extent(separator, srid)
            except:
                pass
        elif self.tipo_de_mapa in ('general'):
            try:
                extents=[]
                for c in self.capas.all():
                    extents+=c.dame_extent([], srid)
                mp=MultiPoint(extents)
                return separator.join(map(str, mp.extent))
            except:
                pass
        return ''
    @property
    def dame_filename(self):
        if '_' in self.id_mapa:
            res = self.id_mapa.split('_',1)[1]
        else:
            res = self.id_mapa
        return res.encode('utf-8')
    def dame_mapserver_size(self):
        try:
            if self.size!='':
                if self.size.count(',')==1:
                    return map(lambda x: int(x),self.size.split(','))
                else:
                    return map(lambda x: int(x),self.size.split())
            return MAPA_DEFAULT_SIZE
        except:
            return MAPA_DEFAULT_SIZE
    # @property
    # devuelve una 4-upla de floats para aplicar al mapObj
    def dame_mapserver_extent(self, srid=4326):
        try:
            if self.extent!='':
                if self.extent.count(',')==3:
                    ext = map(lambda x: float(x), self.extent.split(','))
                else:
                    ext = map(lambda x: float(x), self.extent.split()) # feo, pero permite mas de un espacio entre valores
                minxy = coordConvert(ext[0], ext[1], 4326, srid)
                maxxy = coordConvert(ext[2], ext[3], 4326, srid)
                return [minxy.x, minxy.y, maxxy.x, maxxy.y]
        except:
            return None
    @property
    def dame_imagecolor(self):
        try:
            if self.imagecolor!='':
                if self.imagecolor[0]=='#':
                    return True, self.imagecolor
                else:
                    if self.imagecolor.count(',')==2:
                        return False, map(lambda x: int(x), self.imagecolor.split(','))
                    elif self.imagecolor.count(' ')==2:
                        return False, map(lambda x: int(x), self.imagecolor.split())
            return True, MAPA_DEFAULT_IMAGECOLOR
        except:
            return True, MAPA_DEFAULT_IMAGECOLOR
        
    @property
    def dame_projection(self):
        return unicode(self.srs) if self.srs!='' and RepresentsPositiveInt(self.srs) else str(MAPA_DEFAULT_SRS)

    @property
    def dame_wxs_url(self):
        if self.tipo_de_mapa=='public_layers':
            return urlparse.urljoin(settings.SITE_URL,'/layers/public_wxs/')
        elif self.tipo_de_mapa=='user':
            return urlparse.urljoin(settings.SITE_URL, '/users/'+self.owner.username+'/wxs/')
        elif self.tipo_de_mapa=='layer_original_srs':
            return urlparse.urljoin(settings.SITE_URL,'/layers/wxs/'+unicode(self.id_mapa.replace('_layer_srs',''))+'/')
        elif self.tipo_de_mapa=='layer_raster_band':
            c=self.capas.first()
            if c.wxs_publico:
                return urlparse.urljoin(settings.SITE_URL, '/layers/public_wxs_raster_band/' + unicode(self.id_mapa) + '/')
            else: 
                return urlparse.urljoin(settings.SITE_URL, '/layers/wxs_raster_band/' + unicode(self.id_mapa) + '/')
        elif self.tipo_de_mapa=='layer':
            c=self.capas.first()
            if c.wxs_publico:
                return urlparse.urljoin(settings.SITE_URL,'/layers/public_wxs/'+unicode(self.id_mapa)+'/')

        return urlparse.urljoin(settings.SITE_URL,'/layers/wxs/'+unicode(self.id_mapa)+'/')
    
    @property
    def showAsWMSLayer(self):
        c=self.capas.first()
        if self.tipo_de_mapa == 'layer' or self.tipo_de_mapa == 'layer_raster_band':
            if c is not None:
                return c.mostrarComoWMS()
        return False

    def dame_mapserver_map_def(self):
        es_hexa, color = self.dame_imagecolor
        srid = self.srs if self.tipo_de_mapa == 'layer_original_srs' else self.dame_projection
        bbox = self.dame_extent(',', srid)
        mapExtent = self.extent if self.tipo_de_mapa == 'layer_original_srs' else self.dame_mapserver_extent(int(srid))
        wxs_url = self.dame_wxs_url
        layers = []
        c=self.capas.first()
        enableContextInfo = True
        if self.tipo_de_mapa in ('layer', 'layer_raster_band'):
            enableContextInfo = c.tipo_de_capa != CONST_RASTER
        if self.tipo_de_mapa in ('layer', 'layer_original_srs', 'user', 'general', 'layer_raster_band'):
            mapserverlayers = self.mapserverlayer_set.all().order_by('orden_de_capa','capa__metadatos__titulo')
        elif self.tipo_de_mapa == 'public_layers':
            mapserverlayers = self.mapserverlayer_set.filter(capa__wxs_publico=True).order_by('orden_de_capa')
        for msl in mapserverlayers:
            if self.tipo_de_mapa=='general':
                l=msl.dame_mapserver_layer_def('WMS')
            else:
                l=msl.dame_mapserver_layer_def(msl.dame_layer_connection_type())
                l['metadata']['ows_srs'] = 'epsg:%s epsg:4326 epsg:3857'%(srid) if RepresentsPositiveInt(srid) else 'epsg:4326 epsg:3857'
            layers.append(l)

        data = {
            "idMapa": self.id_mapa,
            "imageColor": {
                "type": "hex" if es_hexa else "rgb",
                "color": color
            },
            "srid": srid,
            "srs": 'epsg:%s'%(srid) if self.srs=='' or RepresentsPositiveInt(self.srs) else self.srs,
            "mapFullExtent": mapExtent,
            "mapBoundingBox": map(lambda x: float(x), bbox.split(',')) if bbox!="" else mapExtent,
            "mapSize": self.dame_mapserver_size,
            "fileName": self.dame_filename,
            "mapType": self.tipo_de_mapa,
            "metadata": {
                "ows_title": unicode(self.dame_titulo).encode('UTF-8'),
                "ows_abstract": unicode(self.dame_descripcion.replace('\r\n', ' ')).encode('UTF-8'),
                "ows_attribution_title": unicode(self.dame_fuente.replace('\r\n', ' ')).encode('UTF-8'),
                "ows_contactorganization": unicode(self.dame_contacto.replace('\r\n', ' ')).encode('UTF-8'),
                "wms_onlineresource": wxs_url,
                "wfs_onlineresource": wxs_url,
                "mg_onlineresource": unicode(self.dame_tilesurl).encode('UTF-8'),
                "mg_siteurl": unicode(settings.SITE_URL).encode('UTF-8'),
                "mg_baselayerurl": self.tms_base_layer.url if self.tms_base_layer else settings.MAPCACHE_URL+'tms/1.0.0/world_borders@GoogleMapsCompatible/{z}/{x}/{y}.png',
                "mg_tmsbaselayer": str(self.tms_base_layer.tms) if self.tms_base_layer else str(True),
                "mg_iswmslayer": str(self.showAsWMSLayer),
                "mg_mapid": unicode(self.id_mapa),
                "mg_layername": unicode(c.nombre) if c is not None else "",
                "mg_enablecontextinfo": str(enableContextInfo),
                "ows_srs": 'epsg:%s epsg:4326 epsg:3857'%(srid) if RepresentsPositiveInt(srid) else 'epsg:4326 epsg:3857', # dejamos proyecciones del mapa y 4326 fijas. esta logica la repetimos en las capas 
                "wfs_getfeature_formatlist": 'geojson,shapezip,csv',
                "ows_encoding": 'UTF-8', # siempre
                "ows_enable_request": '*',
                "labelcache_map_edge_buffer": '10'
            },
            "layers": layers
        }
        
        return data

    def create_mapfile(self, save=True):
        return mapserver.create_mapfile(self.dame_mapserver_map_def(), save)

    def generar_thumbnail_y_legend(self):
        print '...Grabando mapa e imagen de %s (tipo %s)'%(self.id_mapa, self.tipo_de_mapa)
        # mapa=self.dame_mapserver_mapObj()
        # mapa.save(os.path.join(settings.MAPAS_PATH, self.id_mapa+'.map'))
        # print "......mapa guardado %s"%(self.id_mapa+'.map')
        if self.tipo_de_mapa in ('layer_original_srs', 'general', 'layer_raster_band'):
            thumb = self.generar_thumbnail()
            print "......imagen creada: %s"%(thumb)
        if self.tipo_de_mapa in ('general', 'layer', 'layer_raster_band'):
            self.generar_legend()
        return True

    def agregar_a_mapcache(self):
        print "agregar_a_mapcache %s"%(self.id_mapa)
        # rm_tileset(self.id_mapa)
        # Si estamos en una arquitectura distribuida los tiles son locales
        mapcache.remove_tileset(self.id_mapa)
        sld_url = ''
        default_sld_url = ''
        srid = MAPA_DEFAULT_SRS
        if self.tipo_de_mapa in ('layer', 'layer_raster_band'):
            capa = self.mapserverlayer_set.first().capa
            # params = ':%s:%d'%(capa.nombre, MAPA_DEFAULT_SRS)
            layers = capa.nombre
            srid = MAPA_DEFAULT_SRS
            for sld in capa.archivosld_set.all():
                # mapcache.remove_map(self.id_mapa, sld.id)
                # rm_tileset(self.id_mapa, sld.id)
                print "sld #%d - %s"%(sld.id, sld.filename.url)
                # Si estamos en una arquitectura distribuida los tiles son locales
                mapcache.remove_tileset(self.id_mapa, sld.id)
                sld_url = urlparse.urljoin(settings.SITE_URL, sld.filename.url)
                # mapcache.add_map(self.id_mapa, layers, srid, sld.id, sld_url)
                add_or_replace_tileset(self.id_mapa, layers, srid, sld.id, sld_url)
                if sld.default:
                    print "default sld: %s"%(sld.filename.url)
                    default_sld_url = urlparse.urljoin(settings.SITE_URL, sld.filename.url)
        elif self.tipo_de_mapa == 'general':
            layers = 'default'

        # mapcache.add_map(self.id_mapa, layers, srid, '', sld_url)
        add_or_replace_tileset(self.id_mapa, layers, srid, '',  default_sld_url)

    def generar_thumbnail(self):
        mapfile=ManejadorDeMapas.commit_mapfile(self.id_mapa)
        if self.tipo_de_mapa in ('general', 'layer_raster_band'):
            for c in self.capas.all():  # es necesario regenerar todo mapfile inexistente
                ManejadorDeMapas.commit_mapfile(c.id_capa)
            wms_url = mapserver.get_wms_request_url(self.id_mapa, 'default', self.srs, 110, 150, self.dame_extent(',','3857'))
        elif self.tipo_de_mapa=='layer_original_srs':
            c=self.capas.first()
            if (c.srid > 0):
                wms_url = mapserver.get_wms_request_url(self.id_mapa, c.nombre, str(c.srid), 110, 150, c.dame_extent(',', self.srs))
                try:
                    sld=c.archivosld_set.filter(default=True)[0]
                    sld_url = getSldUrl(sld.filename.url)
                    wms_url = mapserver.get_wms_request_url(self.id_mapa, c.nombre, str(c.srid), 110, 150, c.dame_extent(',', self.srs), sld_url)
                except:
                    pass 
            else:
                wms_url = ''
        print wms_url
        thumb=os.path.join(settings.MEDIA_ROOT, self.id_mapa+'.png')
        if wms_url != '':
            return urlToFile(wms_url, thumb)
        else:
            return mapserver.draw_map_to_file(self.id_mapa, thumb)

    def generar_legend(self):
        # capa = self.capas.first()
        mapfile=ManejadorDeMapas.commit_mapfile(self.id_mapa)
        filelist = []
        for mslayer in self.mapserverlayer_set.all():
            if self.tipo_de_mapa == 'layer_raster_band':
                sld = urlparse.urljoin(settings.SITE_URL, mslayer.archivo_sld.filename.url) if mslayer.archivo_sld else None
            else:
                sld = urlparse.urljoin(settings.SITE_URL, mslayer.archivo_sld.filename.url) if mslayer.archivo_sld else mslayer.capa.dame_sld_default()
            url = mapserver.get_legend_graphic_url(self.id_mapa, mslayer.capa.nombre, sld)
            filename=os.path.join(settings.MEDIA_ROOT, self.id_mapa+('_legend_%i.png'%mslayer.orden_de_capa))
            filelist.append(filename)
            try:
                urlToFile(url, filename)
            except:
                print '\nFailed to create legend file %s\n'%filename
                return False
        try:
            call('convert %s -background "rgba(0,0,0,0)" -append %s'%(' '.join(filelist), os.path.join(settings.MEDIA_ROOT, self.id_mapa+'_legend.png')), shell=True)
        except:
            return False
        for filename in filelist:
            try:
                os.remove(filename)
            except:
                return False
        return True

    objects = SearchManager(
        fields = ('input_search_index',), # esa coma final debe ir si o si
        config = 'pg_catalog.spanish', # this is default
        search_field = 'search_index', # this is default
        auto_update_search_field = True
    )

class MapServerLayer(models.Model):
    capa = models.ForeignKey(Capa,null=False,blank=False)
    mapa = models.ForeignKey(Mapa)
    orden_de_capa = models.IntegerField(null=False)
    bandas = models.CharField(null=False, blank=True, max_length=100)   # string que representa una tupla de tipo (<variable>, <bandas>), por ejemplo "('WIND', '3,4')"
    feature_info = models.BooleanField(u'Feature Info', null=False, default=True)
    archivo_sld = models.ForeignKey(ArchivoSLD, null=True, blank=True, on_delete=models.SET_NULL) 

    texto_input = models.TextField(u'Texto Input', null=False, blank=True, max_length=10000)
    texto_output = models.TextField(u'Texto Output', null=False, blank=True, max_length=10000)
    class Meta:
        verbose_name = 'MapServer Layer'
        verbose_name_plural = 'MapServer Layers'
    def __unicode__(self):
        return '%s.%s (%s)'%(unicode(self.mapa),unicode(self.capa),unicode(self.orden_de_capa))

    def dame_layer_connection(self, connectiontype):
        if connectiontype == 'WMS':
            if self.bandas != "":
                return mapserver.get_wms_url(self.bandas)
            else:
                return mapserver.get_wms_url(self.capa.id_capa)
        else:
            return self.capa.dame_connection_string

    def dame_layer_connection_type(self):
        return self.capa.dame_connection_type

    def dame_data(self, srid=None):
        return self.capa.dame_data(srid)

    def save(self, srid=None, *args, **kwargs):
        if self.archivo_sld is not None and self.archivo_sld.capa != self.capa:
            self.archivo_sld = None
        # innecesario por el momento
#         try:
#             mslo=self.dame_mapserver_layerObj()
#             self.texto_output=mslo.convertToString()
#         except:
#             self.texto_output=''
        super(MapServerLayer, self).save(*args, **kwargs)
        ManejadorDeMapas.delete_mapfile(self.mapa.id_mapa)
        return True

    def dame_mapserver_layer_def(self, connectiontype='POSTGIS'):
        include_items, items_aliases = self.capa.metadatos.dame_gml_atributos()
        srid = 4326 if self.mapa.tipo_de_mapa in ('public_layers', 'user') and self.capa.srid != 4326 else int(self.capa.dame_projection)
        if self.capa.tipo_de_capa == CONST_VECTOR:
            data = {
                "connectionType": connectiontype,
                "layerName": self.capa.nombre,
                "layerTitle": self.capa.dame_titulo.encode('utf-8'),
                "layerConnection": self.dame_layer_connection(connectiontype),
                "layerData": self.dame_data(srid),
                "sldUrl": (urlparse.urljoin(settings.SITE_URL, self.archivo_sld.filename.url)) if self.archivo_sld is not None else "",
                "layerType": 'RASTER' if connectiontype == 'WMS' else self.capa.tipo_de_geometria.mapserver_type,
                "srid": srid,
                "metadataIncludeItems": include_items,
                "metadataAliases": items_aliases,
                "layerDefinitionOverride": self.texto_input,
                "metadata": {},
                "driver": self.capa.gdal_driver_shortname,
                "rasterBandInfo": "",
                "proj4": '',
            }

            # print "Data sources #: %d"%len(VectorDataSource.objects.filter(capa=self.capa))
            if len(VectorDataSource.objects.filter(capa=self.capa)) > 1 and connectiontype!='WMS':
                ds = VectorDataSource.objects.filter(capa=self.capa).order_by('data_datetime')
                data["timeItem"] = 'data_datetime'
                data["timeExtent"] = ','.join([rec.data_datetime.replace(second=0,microsecond=0).isoformat() for rec in ds])
                # Por ahora dejo el max...
                data["timeDefault"] = ds.last().data_datetime.replace(second=0,microsecond=0).isoformat()

        elif self.capa.tipo_de_capa == CONST_RASTER:
            data = {
                "connectionType": connectiontype,
                "layerName": self.capa.nombre,
                "layerTitle": self.capa.dame_titulo.encode('utf-8'),
                "layerConnection": self.dame_layer_connection(connectiontype),
                "layerData": self.dame_data(srid),
                "sldUrl": (urlparse.urljoin(settings.SITE_URL, self.archivo_sld.filename.url)) if self.archivo_sld is not None else "",
                "layerType": 'RASTER',
                "srid": srid,
                "metadataIncludeItems": include_items,
                "metadataAliases": items_aliases,
                "layerDefinitionOverride": self.texto_input,
                "metadata": {},
                "driver": self.capa.gdal_driver_shortname,
                "rasterBandInfo": "",
                "proj4": self.capa.proyeccion_proj4,
                "layerExtent": self.capa.layer_srs_extent,
            }

            # print "Data sources #: %d"%RasterDataSource.objects.filter(capa=self.capa).count()
            if RasterDataSource.objects.filter(capa=self.capa).count() > 0 and self.capa.gdal_driver_shortname not in ('netCDF', 'HDF5') and connectiontype!='WMS':
                ds = RasterDataSource.objects.filter(capa=self.capa).order_by('data_datetime')
                data["timeItem"] = 'data_datetime'
                data["tileItem"] = 'location'
                data["timeIndexData"] = self.capa.dame_datasource_data()
                data["timeExtent"] = ','.join([rec.data_datetime.isoformat() for rec in ds])
                # Por ahora dejo el max...
                data["timeDefault"] = ds.last().data_datetime.isoformat()

            # En el caso de GRIB, generamos info extra en rasterBandInfo para aplicar template especifico a posteriori
            if self.capa.gdal_driver_shortname == 'GRIB' and connectiontype!='WMS':
                if self.mapa.tipo_de_mapa == 'layer_raster_band':   # es el caso de una banda específica, tenemos que ver metadatos
                    data['rasterBandInfo'] = (self.bandas, self.capa.gdal_metadata['variables_detectadas'][self.bandas])
                else:                                               # es el caso del mapa por defecto de GRIB, sin variables específicas
                    if len(self.capa.gdal_metadata['variables_detectadas']) > 0:
                        # buscamos la banda de temperatura, aunque podría ser cualquier otra definición, y armamos una tupla
                        # primero una default cualquiera
                        cualquier_banda = self.capa.gdal_metadata['variables_detectadas'].keys()[0]
                        data['rasterBandInfo'] = (cualquier_banda, self.capa.gdal_metadata['variables_detectadas'][cualquier_banda])
                        # luego overrideamos si existe alguna de TMP
                        for banda, variable in self.capa.gdal_metadata['variables_detectadas'].iteritems():
                            if variable['elemento'] == 'TMP':
                                data['rasterBandInfo'] = (banda, variable)

            # En el caso de netCDF y HDF5, solo tenemos que overridear el DATA de la capa
            elif self.capa.gdal_driver_shortname in ('netCDF', 'HDF5') and connectiontype!='WMS':
                prefijo_data = self.capa.gdal_driver_shortname.upper()  # NETCDF|HDF5
                if self.mapa.tipo_de_mapa == 'layer_raster_band':
                    data["layerData"] = '{}:{}'.format(data["layerData"], self.bandas)
                else:
                    # if len(self.capa.gdal_metadata['variables_detectadas']) == 0:
                    if len(self.capa.gdal_metadata['subdatasets']) != 0:
                        # hay subdatasets y es mapa de capa => estamos obligados a renderizar alguno pues mapserver no se banca el render directo en este caso (NETCDF|HDF5:/path/al/archivo:subdataset)
                        primer_subdataset_identificador = self.capa.gdal_metadata['subdatasets'][0]['identificador']   # Ejemplo: "formato:/path/al/archivo:subdataset"
                        data["layerData"] = '{}:{}'.format(data["layerData"], primer_subdataset_identificador)

        return data

    def dame_metadatos_asociado_a_banda(self):
        """ Esta version del metodo tiene en cuenta el raster_layer del mapa actual,
        o sea, solo devuelve metadatos de ese "subproducto", pensado para llamar desde la vista detalle del mapa
        """
        if self.bandas != '':
            if len(self.capa.gdal_metadata['subdatasets']) > 0:
                for b in self.capa.gdal_metadata['subdatasets']:
                    if b.get('identificador') == self.bandas:
                        return [sorted(b['gdalinfo']['metadata'][''].iteritems())]
            else:
                try:
                    res = []
                    bandas = str(self.bandas).split(',')     # array de bandas, Ej: ['4'], ['5', '6']
                    for b in self.capa.gdal_metadata['gdalinfo']['bands']:
                        if str(b['band']) in bandas:
                            metadatos = b['metadata']['']
                            metadatos['BAND'] = b['band']
                            res.append(sorted(metadatos.iteritems()))
                    return res
                except:
                    return []
        else:
            return []

def inicializarMapasDeCapa(instance):
    # ------------ creamos/actualizamos mapas
    # creamos el mapa canónico
    mapa = Mapa(owner=instance.owner, nombre=instance.nombre, id_mapa=instance.id_capa, tipo_de_mapa='layer')
    if instance.tipo_de_capa == CONST_RASTER:
        try:
            print "Intentando setear baselayer..."
            mapa.tms_base_layer = TMSBaseLayer.objects.get(pk=1)
        except:
            pass

    mapa.save(escribir_imagen_y_mapfile=False)
    MapServerLayer(mapa=mapa, capa=instance, orden_de_capa=0).save()
    mapa.save()

    # creamos el mapa en la proyeccion original
    extent_capa = instance.layer_srs_extent
    mapa_layer_srs = Mapa(owner=instance.owner, nombre=instance.nombre + '_layer_srs', id_mapa=instance.id_capa + '_layer_srs', tipo_de_mapa='layer_original_srs', srs=instance.srid, extent=extent_capa)
    # Esto es para cuando tenemos una proyeccion no identificada
    if instance.proyeccion_proj4 is not None and instance.proyeccion_proj4 != '' and not RepresentsPositiveInt(instance.srid):
        print "Seteando proyeccion custom para el mapa {}".format(instance.proyeccion_proj4)
        mapa_layer_srs.srs = instance.proyeccion_proj4

    mapa_layer_srs.save(escribir_imagen_y_mapfile=False)
    MapServerLayer(mapa=mapa_layer_srs, capa=instance, orden_de_capa=0).save()
    mapa_layer_srs.save()

    if instance.tipo_de_capa == CONST_RASTER:
        for bandas, variable in take(settings.CANTIDAD_MAXIMA_DE_BANDAS_POR_RASTER, sorted(instance.gdal_metadata['variables_detectadas'].iteritems())):
            id_banda = str(bandas).replace(',', '_').replace('/', '').replace('\\', '.').lower()
            sufijo_mapa = '_band_{}_{}'.format(id_banda, variable['elemento'].lower())
            mapa = Mapa(
                owner=instance.owner,
                nombre=instance.nombre + sufijo_mapa,
                id_mapa=instance.id_capa + sufijo_mapa,
                titulo='{} - {}{}'.format(bandas, variable['elemento'], ': {}'.format(variable['descripcion']) if variable['descripcion'] != '' else ''),
                tipo_de_mapa='layer_raster_band')
            try:
                print "Intentando setear baselayer..."
                mapa.tms_base_layer = TMSBaseLayer.objects.get(pk=1)
            except:
                pass

            mapa.save(escribir_imagen_y_mapfile=False)
            MapServerLayer.objects.create(
                mapa=mapa,
                capa=instance,
                bandas=bandas,
                orden_de_capa=0)
            mapa.save()

    # actualizamos el mapa de usuario
    ManejadorDeMapas.delete_mapfile(instance.owner.username)

    # actualizamos el mapa de capas públicas
    ManejadorDeMapas.delete_mapfile('mapground_public_layers')


@receiver(post_save, sender=Capa)
def onCapaPostSave(sender, instance, created, **kwargs):
    print 'onCapaPostSave %s'%(str(instance))
    if created:
        print '...capa creada'
        # ------------ creamos y completamos metadatos y atributos
        metadatos = Metadatos.objects.create(capa=instance, titulo=instance.nombre)
        # devuelve <att_num, campo, tipo, default_value, uniq, pk>
        cursor = connection.cursor()
        cursor.execute("SELECT * from utils.campos_de_tabla(%s,%s)", [instance.esquema, instance.tabla])
        rows = cursor.fetchall()
        for r in rows:
            Atributo.objects.create(nombre_del_campo=r[1], tipo=r[2], unico=r[4], metadatos=metadatos)

    else:
        print '...capa actualizada (ya existia)'
        # actualizamos los mapas relacionados con la capa
        ManejadorDeMapas.delete_mapfile('mapground_public_layers')
        for m in instance.mapa_set.filter(tipo_de_mapa__in=['layer', 'layer_original_srs', 'general', 'layer_raster_band']):
            ManejadorDeMapas.delete_mapfile(m.id_mapa)
        for m in Mapa.objects.all().filter(tipo_de_mapa='user'):
            ManejadorDeMapas.delete_mapfile(m.id_mapa)

@receiver(post_save, sender=VectorDataSource)
def onVectorDataSourcePostSave(sender, instance, created, **kwargs):
    tieneMapaCanonico = ManejadorDeMapas.existe_mapa(instance.capa.id_capa)
    print 'onVectorDataSourcePostSave Capa: %s'%(instance.capa.nombre)
    if not tieneMapaCanonico:
        print 'Inicializando mapas de capa %s'%(instance.capa.nombre)
        inicializarMapasDeCapa(instance.capa)

@receiver(post_save, sender=RasterDataSource)
def onRasterDataSourcePostSave(sender, instance, created, **kwargs):
    tieneMapaCanonico = ManejadorDeMapas.existe_mapa(instance.capa.id_capa)
    print '### onRasterDataSourcePostSave Capa: %s'%(instance.capa.nombre)
    if not tieneMapaCanonico:
        print 'Inicializando mapas de capa %s'%(instance.capa.nombre)
        inicializarMapasDeCapa(instance.capa)
    
@receiver(post_delete, sender=MapServerLayer)
def onMapServerLayerPostDelete(sender, instance, **kwargs):
    print 'onMapServerLayerPostDelete %s'%(str(instance))
    ManejadorDeMapas.delete_mapfile(instance.mapa.id_mapa)


@receiver(post_delete, sender=Capa)
def onCapaPostDelete(sender, instance, **kwargs):
    print 'onCapaPostDelete %s'%(str(instance))
    try:
        Mapa.objects.get(id_mapa=instance.id_capa,tipo_de_mapa='layer').delete()
    except:
        pass
    try:
        Mapa.objects.get(id_mapa=instance.id_capa+'_layer_srs',tipo_de_mapa='layer_original_srs').delete()
    except:
        pass
    try:
        Mapa.objects.filter(id_mapa__startswith=instance.id_capa+'_band_',tipo_de_mapa='layer_raster_band').delete()
    except:
        pass
    if instance.tipo_de_capa == CONST_VECTOR:
        try:
            # ERROR Hay que cambiar esto!
            print "Borrando tabla master %s"%(instance.id_capa)
            drop_table(instance.esquema, instance.id_capa, True)
            # TablaGeografica.objects.filter(tabla=instance.id_capa).delete()
        except:
            pass
    elif instance.tipo_de_capa == CONST_RASTER:
        try:
            ArchivoRaster.objects.filter(nombre_del_archivo=instance.nombre_del_archivo, owner=instance.owner)[0].delete()
        except:
            pass
    # Eliminamos la secuencia asociada a versiones de la capa
    try: 
        Sequence.objects.filter(name=instance.id_capa).delete()
    except:
        pass


@receiver(post_delete, sender=Mapa)
def onMapaPostDelete(sender, instance, **kwargs):
    print 'onMapaPostDelete %s'%(str(instance))
    if instance.tipo_de_mapa in ('layer', 'layer_raster_band'):
        # manage.remove([instance.id_mapa])
        mapcache.remove_map(instance.id_mapa)
    try:
        os.remove(os.path.join(settings.MAPAS_PATH, instance.id_mapa+'.map'))
    except:
        pass
    try:  # deberia borrar solo si tipo_de_mapa in ['layer_original_srs', 'general']
        os.remove(os.path.join(settings.MEDIA_ROOT, instance.id_mapa + '.png'))
    except:
        pass

def getSldUrl(sld_file_url):
    return urlparse.urljoin(settings.SITE_URL, sld_file_url)

def generarThumbnailSLD(capa, sld):
    try:
        extent_capa = capa.dame_extent(',', 3857).split(',')
    except:
        print "Error generando preview de capa con SLD!!!"
        return
    e = map(float, extent_capa)
    ex = e[2]-e[0]
    ey = e[3]-e[1]
    z = (ey - ex)/2 if ey > ex else (ex - ey)/2
    e2 = [e[0], e[1]+z, e[2], e[3]-z] if ey > ex else [e[0]+z, e[1], e[2]-z, e[3]]
    extent = ','.join(map(str, e2))
    sld_url = getSldUrl(sld.filename.url)
    mapfile = ManejadorDeMapas.commit_mapfile(capa.id_capa)
    wms_url = mapserver.get_wms_request_url(capa.id_capa, capa.nombre, '3857', 150, 150, extent, sld_url)
    print wms_url
    thumb = os.path.splitext(sld.filename.path)[0]+'.png'
    try:
        urllib.urlretrieve(wms_url, thumb)
    except:
        print "Error generando preview de capa con SLD!!!"

@receiver(post_save, sender=ArchivoSLD)
def onArchivoSLDPostSave(sender, instance, created, **kwargs):
    print 'onArchivoSLDPostSave %s'%(str(instance))
    if instance.default:
        q=ArchivoSLD.objects.filter(capa=instance.capa).exclude(pk=instance.pk)
        q.update(default=False)
    if time.time()-os.path.getctime(instance.filename.path) < 3:
        try:
            # Nos aseguramos que el nombre de la capa en el SLD sea el correcto.
            print "Actualizando nombre de capa en el SLD: %s"%instance.filename.path
            tree = etree.parse(instance.filename.path)
        except:
            print "Error tratando de abrir archivo SLD: %s"%instance.filename.path
        try:
            root = tree.getroot()
            root.findall('*/{http://www.opengis.net/se}Name')[0].text = instance.capa.nombre
            # sizes = root.findall('.//{http://www.opengis.net/se}Size')
            # for s in sizes:
            #     s.text = str(float(s.text)*3.5)
            # stroke_widths = root.findall(".//{http://www.opengis.net/se}SvgParameter[@name='stroke-width']")
            # for s in stroke_widths:
            #     s.text = str(float(s.text)*3.5)
            properties = root.findall('.//{http://www.opengis.net/ogc}PropertyName')
            for p in properties:
                p.text = p.text.lower()
            tree.write(instance.filename.path, encoding='utf-8')
        except:
            print "Error tratando de escribir SLD"
    else:
        print "No se modifico el SLD"
    generarThumbnailSLD(instance.capa, instance)  # siempre
    instance.capa.save()
    ManejadorDeMapas.generar_thumbnail(instance.capa.id_capa + '_layer_srs')


@receiver(post_delete, sender=ArchivoSLD)
def onArchivoSLDPostDelete(sender, instance, **kwargs):
    print 'onArchivoSLDPostDelete {}'.format(str(instance))
    instance.capa.save()
    if instance.default:
        ManejadorDeMapas.generar_thumbnail(instance.capa.id_capa + '_layer_srs')
    try:
        os.remove(os.path.splitext(instance.filename.path)[0] + '.png')
        os.remove(os.path.join(settings.MEDIA_ROOT, instance.filename.name))
    except:
        pass
