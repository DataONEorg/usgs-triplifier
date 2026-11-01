# GNIS Transformation & Loading

The source data is fetched and transformed into RDF with the `usgs_triplifier` package. The data is then loaded into GraphDB, after the repository and its accounts are configured.

## Background

A working GraphDB instance needs the following:
1. GraphDB is started
2. A repository for the data is created
3. Accounts and permissions are configured
4. The data is generated with the `usgs_triplifier` package
5. The data is copied into the GraphDB container and imported

These steps are automated by the code in the `code/` folder. Once GraphDB is ready, `etl.py` configures the repository and accounts, downloads the source data, triplifies it and loads it. *This code is mounted into the same container that GraphDB runs in* and is called by the entrypoint script.
