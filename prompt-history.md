# Prompt 1

Help me create a program to extract all historical data from my solar inverters API.

I have attached multiple files to aid in understanding the inverter and the web portal for data access:
* The inverter model is Sunsynk 5.5kW hybrid inverter, I have attached the inverter user manual
* The inverter uses a datalogger to upload data from the inverter to the Sunsynk Connect portal available here https://sunsynk.net. I have attached the datalogger user manual also
* The Sunsynk Connect portal has an API, which the knowledge base includes an example of how to get your access_token. I've attached this API token HTML file provided with this
* There is a separate web link which I think is used for the API here https://api.sunsynk.net
* sunsynk-api-client-main.zip is a github repository of an API client created 2 years ago
* sunsynk-node-api-client-main.zip is a github repository of another API client created 2 years ago
* sunsynk_get_generation.py is a simple Python script designed to retrieve the plant id and current power generation data from a Sunsynk inverter. I have attached the readme sunsynk_get_generation-readme.txt
* sunsniff-main.zip is a github repository that collects data from a Sunsynk/Deye router and makes it available for use


# Prompt 2

This worked great. I exported data for 2025-02-28 and have attached this as sunsynk_historical_data.csv

We need to make some changes and improvements to the the program:
* Change the BASE_URL to https://api.sunsynk.net, this is what worked
* The API only stores data for 90 days, so we need to add a check for the dates entered if it's before this
* Improve and manipulate the output data structure as in the example sunsnk_historical_data.csv. Currently each line includes a date, label, value and unit, and a new line for each time period throughout the day and a new section for each label. Instead we want this to be easier to read and manipulate by the user. So first all labels in the dataset should be in the first row as part of the header, indicating their units like this [unit]. Then every row after that should just include the data, with the format of datetime and then the value for each label in the dataset. All the numbers of the values are integer, so remove the decimal point from the output too.
* Improve the output file name to include the plant number and the date range exported