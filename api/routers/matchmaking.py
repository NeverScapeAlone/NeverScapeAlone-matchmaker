import json
import logging
import time
from ast import Delete
from dataclasses import replace
from datetime import datetime
from optparse import Option
from pickletools import optimize
from pstats import Stats
from typing import Optional
from urllib.request import Request
from xmlrpc.client import Boolean, boolean

import networkx as nx
import numpy as np
import pandas as pd
from api.database.functions import (
    USERDATA_ENGINE,
    sqlalchemy_result,
)

from api.config import redis_client, VERSION
from api.database.models import ActiveMatches, UserQueue, Users, WorldInformation
from certifi import where
from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi_utils.tasks import repeat_every
from h11 import InformationalResponse
from networkx.algorithms.community import greedy_modularity_communities
from pydantic import BaseModel
from pydantic.fields import Field
from pymysql import Timestamp
from pyparsing import Opt
from requests import delete, options, request, session
from sqlalchemy import TEXT, TIMESTAMP, select, table, tuple_, values
from sqlalchemy.dialects.mysql import Insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql import case, text
from sqlalchemy.sql.expression import Select, insert, select, update

logger = logging.getLogger(__name__)

router = APIRouter()


class user_active_match(BaseModel):
    user_id: int
    user_queue_ID: int
    party_identifier: str
    activity: str
    party_member_count: int


async def build_matchmaking_parties():
    """logic for building matchmaking parties - Runs every 5 seconds."""
    UserQueue_table = UserQueue
    ActiveMatches_table = ActiveMatches
    WorldInformation_table = WorldInformation

    sql = select(UserQueue_table).where(UserQueue_table.in_queue == 1)
    world_sql = select(WorldInformation_table)
    async with USERDATA_ENGINE.get_session() as session:
        session: AsyncSession = session
        async with session.begin():
            data = await session.execute(sql)
            world_data = await session.execute(world_sql)

    df = pd.DataFrame(sqlalchemy_result(data).rows2dict())
    df_world = pd.DataFrame(sqlalchemy_result(world_data).rows2dict())

    if len(df) == 0:
        return

    check_columns = [
        "activity",
        "party_member_count",
        "us",
        "eu_central",
        "eu_west",
        "oceania",
        "f2p",
        "p2p",
    ]
    inverse_columns = ["self_experience_level", "partner_experience_level"]

    # Sets party numbers from grouping methods
    df["party_number"] = df.groupby(by=check_columns).grouper.group_info[0] + 1
    # Counts individual members of a party from party numbers
    df["count"] = df.groupby(["party_number"])["activity"].transform("count")
    # Filters out sections where the count is lower than the party number requested by users
    df = df[df["party_member_count"] <= df["count"]]

    # Obtains the unique party numbers from the tally, this allows the groups to be managed
    unique_party_numbers = df.party_number.unique()
    # Creates a group header for labeling the output data
    group_header = str(int(time.time()))[5:]
    # Creates a party with user ID for final accumulation
    parties_with_userid = dict()

    for pn_c, pn in enumerate(unique_party_numbers):
        mask = df.party_number == pn
        # Gets the sub dataframe relevant to the group
        df_sub = df[mask]

        # obtains party member count from the sub dataframe
        party_member_count = df_sub["party_member_count"].unique()[0]
        # gets party qualifiers
        us = int(df_sub["us"].unique()[0])
        eu_west = int(df_sub["eu_west"].unique()[0])
        eu_central = int(df_sub["eu_central"].unique()[0])
        oceania = int(df_sub["oceania"].unique()[0])
        f2p = int(df_sub["f2p"].unique()[0])
        p2p = int(df_sub["p2p"].unique()[0])

        if f2p ^ p2p:
            if f2p > p2p:
                if us:
                    world = int(
                        df_world[(df_world["f2p"] == 1) & df_world["us"] == 1][
                            "world_number"
                        ]
                        .sample()
                        .values[0]
                    )
                if eu_central:
                    world = int(
                        df_world[(df_world["f2p"] == 1) & df_world["eu_central"] == 1][
                            "world_number"
                        ]
                        .sample()
                        .values[0]
                    )
                if eu_west:
                    world = int(
                        df_world[(df_world["f2p"] == 1) & df_world["eu_west"] == 1][
                            "world_number"
                        ]
                        .sample()
                        .values[0]
                    )
                if oceania:
                    world = int(
                        df_world[(df_world["f2p"] == 1) & df_world["oceania"] == 1][
                            "world_number"
                        ]
                        .sample()
                        .values[0]
                    )
            else:
                if us:
                    world = int(
                        df_world[(df_world["p2p"] == 1) & df_world["us"] == 1][
                            "world_number"
                        ]
                        .sample()
                        .values[0]
                    )
                if eu_central:
                    world = int(
                        df_world[(df_world["p2p"] == 1) & df_world["eu_central"] == 1][
                            "world_number"
                        ]
                        .sample()
                        .values[0]
                    )
                if eu_west:
                    world = int(
                        df_world[(df_world["p2p"] == 1) & df_world["eu_west"] == 1][
                            "world_number"
                        ]
                        .sample()
                        .values[0]
                    )
                if oceania:
                    world = int(
                        df_world[(df_world["p2p"] == 1) & df_world["oceania"] == 1][
                            "world_number"
                        ]
                        .sample()
                        .values[0]
                    )
        else:
            if us:
                world = int(
                    df_world[(df_world["p2p"] == 1) & df_world["us"] == 1][
                        "world_number"
                    ]
                    .sample()
                    .values[0]
                )
            if eu_central:
                world = int(
                    df_world[(df_world["p2p"] == 1) & df_world["eu_central"] == 1][
                        "world_number"
                    ]
                    .sample()
                    .values[0]
                )
            if eu_west:
                world = int(
                    df_world[(df_world["p2p"] == 1) & df_world["eu_west"] == 1][
                        "world_number"
                    ]
                    .sample()
                    .values[0]
                )
            if oceania:
                world = int(
                    df_world[(df_world["p2p"] == 1) & df_world["oceania"] == 1][
                        "world_number"
                    ]
                    .sample()
                    .values[0]
                )
        # obtains the activity name from the sub dataframe
        activity_name = df_sub["activity"].values[0]

        # obtains an array from the sub dataframe which contains the skill level values for self and partner
        arr = np.array(df_sub[inverse_columns].values)
        X_self, Y_partner = np.split(arr, 2, axis=1)
        X, Y = X_self.flatten(), Y_partner.flatten()

        # Gets the paired values and sorts them according to lower -> upper values in pairs. This makes future sorting easier.
        pair_values = []
        for cx, x in enumerate(X):
            for cy, y in enumerate(Y):
                if x >= y:
                    if cx > cy:
                        pair_values.append([cy, cx])
                    if cy > cx:
                        pair_values.append([cx, cy])

        pair_values = np.array(pair_values)
        u, c = np.unique(pair_values, axis=0, return_counts=True)
        # Gets pairs where there is a mutual acceptance for the other skill level. Ex. Both users want to play with eachother.
        paired = u[np.where(c >= 2)]

        # continues if length of the paired array is zero, meaning that there's no mutual want for the other skill level.
        if len(paired) == 0:
            continue

        # Builds a network from the paired listings
        G = nx.from_edgelist(paired)

        # Gets communities from listings, and fragments on a 1.1 resolution
        c = list(greedy_modularity_communities(G, resolution=1.1))

        # shows created parties in group
        created_parties = dict()
        for group_number, group in enumerate(c):
            user_position_in_party = []

            if len(group) < party_member_count:
                # if the amount of members in the group is lower than the requested count, remove
                continue
            for user_number, user in enumerate(group):
                # collect users that will be in the group
                if (user_number + 1) > party_member_count:
                    continue
                user_position_in_party.append(user)
            created_parties[group_number] = user_position_in_party

        # continues loop if the number of created parties is equal to zero
        if len(created_parties) == 0:
            continue

        # shows party grouping with user ids
        for prty_number in created_parties:
            user_ids = []
            user_queue_IDs = []
            for user_position in created_parties[prty_number]:
                user_id = df_sub.user_id.values[user_position]

                mask = (df_sub.user_id == user_id) & (df_sub.activity == activity_name)
                user_queue_ID = df_sub[mask].ID.values[0]

                user_ids.append(user_id)
                user_queue_IDs.append(user_queue_ID)

            parties_with_userid[
                f"{activity_name}"
                + "$"
                + str(party_member_count)
                + "@"
                + group_header
                + "_"
                + str(pn_c)
                + "_"
                + str(prty_number)
                + "&world="
                + str(world)
            ] = list(zip(user_ids, user_queue_IDs))

    values = []
    for party in parties_with_userid:
        for party_userid, party_user_queue_ID in parties_with_userid[party]:
            value = user_active_match(
                user_id=party_userid,
                user_queue_ID=party_user_queue_ID,
                party_identifier=party,
                activity=party[: party.find("$")],
                party_member_count=int(party[party.find("$") + 1 : party.find("@")]),
            )
            values.append(value.dict())

    # if no values to send
    if len(values) == 0:
        return

    sql = insert(ActiveMatches_table).values(values).prefix_with("ignore")

    async with USERDATA_ENGINE.get_session() as session:
        session: AsyncSession = session
        async with session.begin():
            await session.execute(sql)

    return
