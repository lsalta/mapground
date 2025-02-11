from rest_framework import serializers

from django.contrib.auth.models import User
from fileupload.models import Archivo
from layers.models import Capa, Categoria, Metadatos, VectorDataSource, RasterDataSource, CONST_RASTER


class UserSerializer(serializers.ModelSerializer):

    class Meta:
        model = User
        fields = ('username', 'email', 'is_staff')


class ArchivoSerializer(serializers.ModelSerializer):
    class Meta():
        model = Archivo
        fields = ('file', 'slug', 'nombre', 'extension')


class RasterDataSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = RasterDataSource
        fields = ('id', 'nombre_del_archivo', 'gdal_driver_longname', 'cantidad_de_bandas',
                  'srid', 'proyeccion_proj4', 'data_datetime', 'timestamp_modificacion')


class VectorDataSourceSerializer(serializers.ModelSerializer):

    class Meta:
        model = VectorDataSource
        fields = ('id', 'tabla', 'cantidad_de_registros',
                  'srid', 'proyeccion_proj4', 'data_datetime', 'timestamp_modificacion')


class DataSourceDateTimeSerializer(serializers.Serializer):
    data_datetime = serializers.DateTimeField()

    def update(self, instance, validated_data):
        instance.data_datetime = validated_data.get('data_datetime', instance.data_datetime)
        instance.save()
        return instance


class CapaSerializer(serializers.ModelSerializer):
    owner = serializers.ReadOnlyField(source='owner.username')
    # rasterdatasources = serializers.SerializerMethodField()
    # vectordatasources = serializers.SerializerMethodField()
    rasterdatasources = RasterDataSourceSerializer(many=True, read_only=True)
    vectordatasources = VectorDataSourceSerializer(many=True, read_only=True)

    class Meta:
        model = Capa
        fields = ('id', 'id_capa', 'slug', 'owner', 'nombre', 'tipo_de_capa', 'srid', 'proyeccion_proj4',
                  'cantidad_de_registros', 'layer_srs_extent', 'wxs_publico',
                  'timestamp_alta', 'timestamp_modificacion', 'rasterdatasources', 'vectordatasources')

    # def get_rasterdatasources(self, instance):
    #     rds = instance.rasterdatasources.all().order_by('timestamp_modificacion')
    #     return RasterDataSourceSerializer(rds, many=True).data

    # def get_vectordatasources(self, instance):
    #     vds = instance.vectordatasources.all().order_by('timestamp_modificacion')
    #     return VectorDataSourceSerializer(vds, many=True).data

    def update(self, instance, validated_data):
        dss_data = validated_data.pop('rasterdatasources') if instance.tipo_de_capa == CONST_RASTER else validated_data.pop('vectordatasources')
        dss = (instance.rasterdatasources).all() if instance.tipo_de_capa == CONST_RASTER else (instance.vectordatasources).all()
        dss = list(dss)
        instance.nombre = validated_data.get('nombre', instance.nombre)
        instance.id_capa = validated_data.get('id_capa', instance.id_capa)
        instance.srid = validated_data.get('srid', instance.srid)
        instance.save()

        for ds_data in dss_data:
            ds = dss.pop(0)
            ds.data_datetime = ds_data.get('data_datetime', ds.data_datetime)
            ds.save()
        return instance


class CategoriaSerializer(serializers.ModelSerializer):

    class Meta:
        model = Categoria
        fields = ('nombre', )


class MetadatosSerializer(serializers.ModelSerializer):

    class Meta:
        model = Metadatos
        fields = (
            'id', 'capa', 'nombre_capa', 'slug_capa',
            'titulo', 'descripcion', 'fuente', 'contacto', 'escala',
            'area_tematica', 'palabras_claves', 'categorias',
            'fecha_de_relevamiento', 'fecha_de_actualizacion', 'frecuencia_de_actualizacion',
            'timestamp_alta', 'timestamp_modificacion',
        )

    escala = serializers.CharField(source="escala.nombre", default='')
    area_tematica = serializers.CharField(source="area_tematica.nombre", default='')
    categorias = CategoriaSerializer(many=True, read_only=True)


class TokenSerializer(serializers.Serializer):
    """
    This serializer serializes the token data
    """
    token = serializers.CharField(max_length=255)
