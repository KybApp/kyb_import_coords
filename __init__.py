def classFactory(iface):
    from .plugin import ImportCoordsPlugin
    return ImportCoordsPlugin(iface)