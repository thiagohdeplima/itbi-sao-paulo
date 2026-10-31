{ pkgs, lib, config, inputs, ... }:

let
  nominatim = pkgs.nominatim.overridePythonAttrs (old: {
    dependencies = old.dependencies ++ (with pkgs.python3Packages; [ falcon uvicorn ]);
  });

  nominatimServer = pkgs.python3.withPackages (ps: [
    ps.nominatim-api
    ps.falcon
    ps.uvicorn
  ]);

  database = {
    name = "nominatim";
    user = "nominatim";
    password = "nominatim";
  };

  nominatimDsn =
    "pgsql:dbname=${database.name};host=${config.env.PGHOST};port=${toString config.env.PGPORT};user=${database.user};password=${database.password}";
in
{
  packages = with pkgs; [ postgresql.pkgs.postgis osm2pgsql nominatim ];

  env = {
    NOMINATIM_DATABASE_DSN = nominatimDsn;
    NOMINATIM_DATABASE_WEBUSER = database.user;
    NOMINATIM_PROJECT_DIR = "${config.env.DEVENV_STATE}/nominatim";
    NOMINATIM_API_URL = "http://127.0.0.1:8080";
    # Four workers with four database connections each. Tune with real queries.
    NOMINATIM_WORKERS = lib.mkDefault "4";
    NOMINATIM_API_POOL_SIZE = lib.mkDefault "4";
  };

  services.postgres = {
    enable = true;
    port   = 61213;

    # Nominatim creates its database and extensions during the import.
    createDatabase = false;

    extensions = pgFinal: [
      pkgs.postgresql.pkgs.postgis
    ];

    initialScript = ''
      CREATE ROLE ${database.user} WITH LOGIN SUPERUSER PASSWORD '${database.password}';
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

  processes = {
    jupyter = {
      after = [ "devenv:processes:nominatim" ];

      exec = "poetry run jupyter lab --ServerApp.token=''";
    };

    nominatim = {
      after = [ "devenv:processes:postgres" ];

      exec = ''
        mkdir -p "$NOMINATIM_PROJECT_DIR"

        cd "$NOMINATIM_PROJECT_DIR"

        exec ${nominatimServer}/bin/uvicorn \
          nominatim_api.server.falcon.server:run_wsgi --factory \
          --host 127.0.0.1 --port 8080 --workers "$NOMINATIM_WORKERS" \
          --no-access-log
      '';
      ready.http.get = {
        port = 8080;
        path = "/status";
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

        wget -c "$DEFAULT_SRC" -O "$DEFAULT_DST" && \
          mkdir -p "$NOMINATIM_PROJECT_DIR" && \
          exec ${nominatim}/bin/nominatim import \
            --project-dir "$NOMINATIM_PROJECT_DIR" --osm-file "$DEFAULT_DST"
      '';
    };
  };
}
