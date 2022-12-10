#!/usr/bin/python

import urllib.request
import simplejson
import datetime
import decimal
import time
import os
import sys
import pathlib
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.colors as colors
import numpy as np
import operator

# We limit the number of API calls to a sane maximum of 50
MAX_API_CALLS = 50
# Also, we sleep between API calls for some time
SLEEP_TIME = 1
# aWATTar API gives data from this day on
DATA_START_DATE = datetime.date(2013,12,22)
cmap=colors.LinearSegmentedColormap.from_list('gr',["g", "y", "r"], N=256)
YMIN = -50
YMAX = 600


data = []

# only works for sorted lists
def get_percentil(l,p):
    return l[round((len(l)-1)*p)] 

def load_data(filename):
    global data
    data = []
    last_start_ts, last_end_ts = 0, 0
    with open(filename, "r") as csvfile:
        for line in csvfile.readlines():
            line = line.strip("\n")
            if line:
                start_ts, end_ts, marketprice, unit = line.strip('\n').split(';')
                start_ts = int(start_ts)
                end_ts = int(end_ts)
                marketprice = decimal.Decimal(marketprice)
                # unit should always be constant, didn't see any other data
                if not unit == "Eur/MWh":
                    raise ValueError(f"unknown unit {unit} in line {line}")
                # also, our data should always be in ascending order
                if last_start_ts >= start_ts or last_end_ts >= end_ts:
                    raise ValueError(f"line {line} is not properly ordered!")
                # data should have no "holes"
                if last_end_ts != start_ts and last_end_ts != 0:
                    raise ValueError(f"data from {last_end_ts} to {start_ts} is missing!")
                if end_ts - start_ts != 3600000:
                    raise ValueError(f"interval {start_ts} - {end_ts} is not a hour")
                # everything good, proceed with next line
                data.append((start_ts, end_ts, marketprice))
                last_start_ts, last_end_ts = start_ts, end_ts


def save_data(filename):
    with open(filename, "w") as csvfile:
        for d in data:
            start_ts, end_ts, marketprice = d
            csvfile.write(f"{start_ts};{end_ts};{marketprice};Eur/MWh\n")

def get_missing_data():
    global data
    _, last_end_ts, __ = data[-1]
    print(f"Data ends at timestamp {last_end_ts} ({datetime.datetime.fromtimestamp(last_end_ts // 1000)})")
    now_ts = int(datetime.datetime.now().timestamp()*1000)
    print(f"There are {max(0,int((now_ts-last_end_ts)//1000//3600//24))} days missing.")

    api_calls = 0
    while last_end_ts < now_ts:
        api_calls += 1
        url = f"https://api.awattar.de/v1/marketdata?start={last_end_ts}"
        print(f"GET {url}")
        with urllib.request.urlopen(url) as u:
            json_data = simplejson.loads(u.read().decode(), use_decimal=True)
            assert(json_data["url"] == "/de/v1/marketdata")
            assert(json_data["object"] == "list")
            json_data = json_data["data"]
            for line in json_data:
                start_ts = int(line["start_timestamp"])
                end_ts   = int(line["end_timestamp"])
                marketprice = decimal.Decimal(line["marketprice"])
                unit = line["unit"]
                # unit should always be constant, didn't see any other data
                if not unit == "Eur/MWh":
                    raise ValueError(f"unknown unit {unit} in line {line}")
                if start_ts != last_end_ts:
                    raise ValueError(f"probable API bug? {start_ts} is not {last_end_ts}")
                data.append((start_ts, end_ts, marketprice))
                last_end_ts = end_ts
        time.sleep(SLEEP_TIME)
        if api_calls >= MAX_API_CALLS:
            print(f"Aborting because we have reached maximum number {api_calls} of API calls.")
            break

def update():
    load_data("historical_data.csv")
    get_missing_data()
    save_data("historical_data.csv")

def bisect(ts):
    if ts < data[0][0] or ts >= data[-1][1]:
        return None
    l,r = 0, len(data)
    while not r-l == 1:
        m = (r+l)//2
        if data[m][0] > ts:
            r = m
        else:
            l = m
    return l

def get_daily_data(d):
    start_ts = int(datetime.datetime(d.year,d.month,d.day,0,0).timestamp())*1000
    d += datetime.timedelta(days=1)
    end_ts   = int(datetime.datetime(d.year,d.month,d.day,0,0).timestamp())*1000 - 1
    start_index = bisect(start_ts)
    end_index = bisect(end_ts)
    return [i[2] for i in data[start_index:end_index+1]]

# Input: list of prices 
#    [ 1.02, 3.20, 4.22, ... ]
# Output: Tuples of hours and list of price
#    [ ("00", 1.02), ("01", 3.20), ("02", 4.22), ... ]
# Please note that there are days which only have 23 or 25 hours (daylight saving)!
# Then, the hour "02" is skipped, or there is "02a" and "02b"
def name_hours(length, short=False):
    if length == 24:
        # normal day without daylight saving adjustment
        return [f"{i:02}" for i in range(24)]
    elif length == 23:
        return [f"{i:02}" for i in range(24) if i != 2]
    elif length == 25 and short == False:
        return ["00", "01", "02a", "02b"] + [f"{i:02}" for i in range(3,24)]
    elif length == 25 and short == True:
        return ["00", "01", "02", "02"] + [f"{i:02}" for i in range(3,24)]
    else:
        assert(False)


def calculate():
    load_data("historical_data.csv")
    _, last_end_ts, __ = data[-1]
    end_date = datetime.datetime.fromtimestamp(last_end_ts//1000).date() - datetime.timedelta(days=1)
    cur_date = DATA_START_DATE

    data_by_day = {}
    data_by_month = {}
    data_by_year = {}
  
    pathlib.Path("out/data/daily/").mkdir(parents=True, exist_ok=True)
    pathlib.Path("out/data/monthly/").mkdir(parents=True, exist_ok=True)
    pathlib.Path("out/data/yearly/").mkdir(parents=True, exist_ok=True)
    pathlib.Path("out/plot/daily/").mkdir(parents=True, exist_ok=True)
    pathlib.Path("out/plot/monthly/").mkdir(parents=True, exist_ok=True)
    pathlib.Path("out/plot/yearly/").mkdir(parents=True, exist_ok=True)

    while cur_date <= end_date:
        d = get_daily_data(cur_date)
        
        # daily calculations 
        data_by_day[cur_date] = d

        # create daily file
        with open(f"out/data/daily/{cur_date}.txt", "w") as f:
            for hour, value in zip(name_hours(len(d)), d):
                f.write(f"{hour};{value}\n")

        # plot day chart
        c = list(map(cmap, [int((float(i)-YMIN)/(YMAX-YMIN)*256) for i in d]))
        plt.figure(figsize=(4096/300, 2160/300), dpi=300)
        plt.bar(name_hours(len(d)),d, align="edge", color=c)
        plt.title(f"{cur_date}")
        plt.xticks(np.arange(len(d)), name_hours(len(d)))
        plt.xlabel("hour of day")
        plt.yticks(np.arange(YMIN, YMAX, step=50))
        plt.ylabel("Eur/MWh")
        plt.ylim(YMIN,YMAX)
        plt.axhline(0)
        plt.savefig(f"out/plot/daily/{cur_date}.png", dpi=300)
        plt.tight_layout()
        plt.close()

        # add to month histogram
        month = f"{cur_date.year}-{cur_date.month:02}"
        if not month in data_by_month:
            data_by_month[month] = {}
        for hour, value in zip(name_hours(len(d), short=True), d):
            if not hour in data_by_month[month]:
                data_by_month[month][hour] = []
            data_by_month[month][hour].append(value)

        # add to year histogram
        year= f"{cur_date.year}"
        if not year in data_by_year:
            data_by_year[year] = {}
        for hour, value in zip(name_hours(len(d), short=True), d):
            if not hour in data_by_year[year]:
                data_by_year[year][hour] = []
            data_by_year[year][hour].append(value)

        print(f"calculated {cur_date}")
        cur_date += datetime.timedelta(days=1)

        # -- end of while loop iterating through days --

    print("starting final calculations")
    for m,v in data_by_month.items():
        for h in name_hours(24, short=True):
            data_by_month[m][h] = sorted(v[h])
    for y,v in data_by_year.items():
        for h in name_hours(24, short=True):
            data_by_year[y][h] = sorted(v[h])

    # monthly values 
    for m,v in data_by_month.items():
        with open(f"out/data/monthly/{m}-average.txt", "w") as f:
            for h in name_hours(24, short=True):
                f.write(f"{h};{sum(v[h])/len(v[h])}\n")
        with open(f"out/data/monthly/{m}-min.txt", "w") as f:
            for h in name_hours(24, short=True):
                f.write(f"{h};{min(v[h])}\n")
        with open(f"out/data/monthly/{m}-max.txt", "w") as f:
            for h in name_hours(24, short=True):
                f.write(f"{h};{max(v[h])}\n")
        with open(f"out/data/monthly/{m}-median.txt", "w") as f:
            for h in name_hours(24, short=True):
                f.write(f"{h};{get_percentil(v[h],0.5)}\n")

    # yearly values  
    for y,v in data_by_year.items():
        with open(f"out/data/yearly/{y}-average.txt", "w") as f:
            for h in name_hours(24, short=True):
                f.write(f"{h};{sum(v[h])/len(v[h])}\n")
        with open(f"out/data/yearly/{y}-min.txt", "w") as f:
            for h in name_hours(24, short=True):
                f.write(f"{h};{min(v[h])}\n")
        with open(f"out/data/yearly/{y}-max.txt", "w") as f:
            for h in name_hours(24, short=True):
                f.write(f"{h};{max(v[h])}\n")
        with open(f"out/data/yearly/{y}-median.txt", "w") as f:
            for h in name_hours(24, short=True):
                f.write(f"{h};{get_percentil(v[h],0.5)}\n")

    # monthly percentile plot
    for m,v in data_by_month.items():
        p0, p10, p50, p90, p100 = [], [], [], [], []
        for h in name_hours(24, short=True):
            p0.append(get_percentil(v[h], 0.0))
            p10.append(get_percentil(v[h], 0.1))
            p50.append(get_percentil(v[h], 0.5))
            p90.append(get_percentil(v[h], 0.9))
            p100.append(get_percentil(v[h], 1.0))
        plt.figure(figsize=(4096/300, 2160/300), dpi=300)
        plt.bar(name_hours(24, short=True), list(map(operator.sub, p10,  p0)),  bottom=p0,  align="edge", color="green")
        plt.bar(name_hours(24, short=True), list(map(operator.sub, p50,  p10)), bottom=p10, align="edge", color="lime")
        plt.bar(name_hours(24, short=True), list(map(operator.sub, p90,  p50)), bottom=p50, align="edge", color="orange")
        plt.bar(name_hours(24, short=True), list(map(operator.sub, p100, p90)), bottom=p90, align="edge", color="red")
        plt.title(f"0/0.1/0.5/0.9/1.0 percentiles for {m}")
        plt.xticks(np.arange(24), name_hours(24,short=True))
        plt.xlabel("hour of day")
        plt.yticks(np.arange(YMIN, YMAX, step=50))
        plt.ylabel("Eur/MWh")
        plt.ylim(YMIN,YMAX)
        plt.axhline(0)
        plt.savefig(f"out/plot/monthly/{m}.png", dpi=300)
        plt.tight_layout()
        plt.close()



    # yearly percentile plot
    for y,v in data_by_year.items():
        p0, p10, p50, p90, p100 = [], [], [], [], []
        for h in name_hours(24, short=True):
            p0.append(get_percentil(v[h], 0.0))
            p10.append(get_percentil(v[h], 0.1))
            p50.append(get_percentil(v[h], 0.5))
            p90.append(get_percentil(v[h], 0.9))
            p100.append(get_percentil(v[h], 1.0))
        plt.figure(figsize=(4096/300, 2160/300), dpi=300)
        plt.bar(name_hours(24, short=True), list(map(operator.sub, p10,  p0)),  bottom=p0,  align="edge", color="green")
        plt.bar(name_hours(24, short=True), list(map(operator.sub, p50,  p10)), bottom=p10, align="edge", color="lime")
        plt.bar(name_hours(24, short=True), list(map(operator.sub, p90,  p50)), bottom=p50, align="edge", color="orange")
        plt.bar(name_hours(24, short=True), list(map(operator.sub, p100, p90)), bottom=p90, align="edge", color="red")
        plt.title(f"0/0.1/0.5/0.9/1.0 percentiles for {y}")
        plt.xticks(np.arange(24), name_hours(24,short=True))
        plt.xlabel("hour of day")
        plt.yticks(np.arange(YMIN, YMAX, step=50))
        plt.ylabel("Eur/MWh")
        plt.ylim(YMIN,YMAX)
        plt.axhline(0)
        plt.savefig(f"out/plot/yearly/{y}.png", dpi=300)
        plt.tight_layout()
        plt.close()


    

def print_usage():
    print("awattar-statistics.py")    
    print("---------------------")
    print("")
    print("This is a simple script which Klaus Eisentraut wrote in order to get")
    print("a rough idea about the EPEX Day-Ahead price and how much the aWATTar")
    print("HOURLY dynamic power contract will cost him in reality.")
    print("")
    print("Usage:")
    print("")
    print("  ./awattar-statistics.py update")
    print("     download missing historical data")
    print("")
    print("  ./awattar-statistics.py calculate")
    print("     create interesting statistics and write them to the output folder")
    print("")
    print("Usually you should run \"update\" first, then \"calculate\".")
    print("Afterwards, look into the graphs in the ./out/ folder.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print_usage()
        sys.exit(1)
    if sys.argv[1] == "update":
        update()
    elif sys.argv[1] == "calculate":
        calculate()
    else:
        print_usage()
        sys.exit(1)
