{ pkgs, lib, config, inputs, ... }:

{
  packages = with pkgs; [ postgresql.pkgs.postgis osm2pgsql ];

  services.postgres = {
    enable = true;
    port   = 61213;

    initialDatabases = [
      {
        name = "appdtb";
        user = "appusr";
        pass = "abc123";

        initialSQL = ''
          CREATE EXTENSION postgis;
          CREATE EXTENSION hstore;
        '';
      }
    ];

    extensions = pgFinal: [
      pkgs.postgresql.pkgs.postgis
    ];

    initialScript = ''
      CREATE ROLE postgres WITH LOGIN SUPERUSER;
    '';
  };

  languages = {
    python = {
      enable = true;

      poetry = {
        enable = true;

        install.enable  = true;
        activate.enable = true;
      };
    };
  };

  scripts = {
    download-and-import-osm = {
      exec = ''
        DEFAULT_SRC="https://download.geofabrik.de/south-america/brazil/sudeste-latest.osm.pbf"
        DEFAULT_DST="$DEVENV_ROOT/tmp/sudeste-latest.osm.pbf"

        if [ "$1" != "" ]; then
          DEFAULT_SRC="$1"
          DEFAULT_DST="$DEVENV_ROOT/tmp"
        fi

        if [ ! -d "$(dirname $DEFAULT_DST)" ]; then
          mkdir -p "$DEFAULT_DST"
        fi

        wget -c $DEFAULT_SRC -O $DEFAULT_DST && \
          osm2pgsql -d appdtb -U appusr --create --slim --hstore --latlong $DEFAULT_DST
      '';
    };
  };
}
