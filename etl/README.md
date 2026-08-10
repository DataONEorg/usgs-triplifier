# GNIS Transformation & Loading

Uses the `usgs_triplifier` package to fetch and transform the source data into RDF. Then configures and uploads the data to GraphDB

## Background

A couple of things need to happen to get a fully working GraphDB instance:
1. GraphDB has to spin up
2. A new repository to hold the data needs to be created
3. Accounts and permissions need to be configured
4. The data needs to be generated (using the `usgs_triplifier` package)
5. The data needs to be uploaded to GraphDB, then told to ingest it

These operations have been automated with the code in the `code/` folder. when GraphDB is in a ready state, the process of configuring a new GraphDB instance in a new container, downloading, triplifying, and uploading is done by calling `etl.py`. *This code is mounted into the same container that GraphDB runs in* and is called by the entrypoint script.
