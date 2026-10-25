# RFC-035E — SOURCE_REPLICATION

Replication of the published relation over the source's own calendar window, on independently reconstructed data, using the frozen spec.

```json
{
  "artifact": "SOURCE_REPLICATION",
  "spec_version": "FALCONX_REPLICATION_SPEC_V1",
  "spec_digest": "d362d6d75129d2337fb1fa4b3434dc8b1412f059816f7091f9e76dc48b8bb9cf",
  "dataset_hash": "b58adaa74e7c73f93d6c4270eba673b88216727e4ee0c133de5334a354134900",
  "window": {
    "start": "2024-01-11",
    "end": "2024-10-11",
    "sessions_in_window": 197
  },
  "source_claim": {
    "granger_F": 8.4767,
    "granger_p": 0.00406,
    "lagged_flow_coefficient_on_price": 0.027,
    "flow_persistence_coefficient": 0.533,
    "price_momentum_coefficient": 0.802,
    "correlation_flows_vs_price": 0.3,
    "impulse_response_peak": "about +1.2% at days 3-4"
  },
  "combinations": [
    {
      "price_var": "r1",
      "flow_var": "flow",
      "sessions": 195,
      "sessions_in_window": 197,
      "regression_n": 194,
      "first_date": "2024-01-15",
      "last_date": "2024-10-11",
      "contemporaneous": {
        "pearson": 0.41267562180535383,
        "spearman": 0.4526436744404343
      },
      "persistence": {
        "ar1": 0.5723627841740533,
        "t": 9.659132306713905,
        "p": 3.0623986231074777e-18,
        "n": 194
      },
      "var1": {
        "n": 194,
        "price_equation": {
          "lag_price_coefficient": -0.14475151978688047,
          "lag_price_t": -1.8445436948057892,
          "lag_flow_coefficient": 2.342561165094671e-05,
          "lag_flow_t": 2.0033135176913004,
          "lag_flow_p": 0.046557236280923404,
          "r2": 0.02684846747785563
        },
        "flow_equation": {
          "lag_price_coefficient": 1420.5733297956476,
          "lag_price_t": 3.3423834918433006,
          "lag_price_p": 0.0009993479697538808,
          "lag_flow_coefficient": 0.485450295847931
        },
        "granger_flow_to_price": {
          "F": 4.013265050165147,
          "p": 0.04655723628091033,
          "df1": 1,
          "df2": 191
        },
        "granger_price_to_flow": {
          "F": 58.75693261469574,
          "p": 8.786415761160498e-13,
          "df1": 1,
          "df2": 191
        },
        "coefficients": {
          "price_equation": [
            0.00010904227271512287,
            -0.14475151978688047,
            2.342561165094671e-05
          ],
          "flow_equation": [
            45.73643269740721,
            1420.5733297956476,
            0.485450295847931
          ]
        }
      }
    },
    {
      "price_var": "r1",
      "flow_var": "sum7",
      "sessions": 190,
      "sessions_in_window": 197,
      "regression_n": 189,
      "first_date": "2024-01-22",
      "last_date": "2024-10-11",
      "contemporaneous": {
        "pearson": 0.10178485686473329,
        "spearman": 0.118655276935795
      },
      "persistence": {
        "ar1": 0.9555570528749266,
        "t": 44.21140256379874,
        "p": 5.988254612102102e-101,
        "n": 189
      },
      "var1": {
        "n": 189,
        "price_equation": {
          "lag_price_coefficient": -0.08149027700906346,
          "lag_price_t": -1.1135551613776193,
          "lag_flow_coefficient": 7.853013694592047e-07,
          "lag_flow_t": 0.32661445943675804,
          "lag_flow_p": 0.7443267370024464,
          "r2": 0.006860910540315568
        },
        "flow_equation": {
          "lag_price_coefficient": 2864.339618969998,
          "lag_price_t": 4.553375703114356,
          "lag_price_p": 9.523718981855121e-06,
          "lag_flow_coefficient": 0.9457728718094403
        },
        "granger_flow_to_price": {
          "F": 0.10667700511582486,
          "p": 0.7443267369993868,
          "df1": 1,
          "df2": 186
        },
        "granger_price_to_flow": {
          "F": 2094.005796953508,
          "p": 3.6436302203763777e-103,
          "df1": 1,
          "df2": 186
        },
        "coefficients": {
          "price_equation": [
            0.0020688019526889268,
            -0.08149027700906346,
            7.853013694592047e-07
          ],
          "flow_equation": [
            28.99929125832009,
            2864.339618969998,
            0.9457728718094403
          ]
        }
      }
    },
    {
      "price_var": "r1",
      "flow_var": "nd",
      "sessions": 183,
      "sessions_in_window": 197,
      "regression_n": 182,
      "first_date": "2024-01-31",
      "last_date": "2024-10-11",
      "contemporaneous": {
        "pearson": 0.11355657913648606,
        "spearman": 0.13279236800263175
      },
      "persistence": {
        "ar1": 0.9059691614002573,
        "t": 28.478972982047154,
        "p": 1.3885004103620035e-68,
        "n": 182
      },
      "var1": {
        "n": 182,
        "price_equation": {
          "lag_price_coefficient": -0.09513558708563634,
          "lag_price_t": -1.2706992207071421,
          "lag_flow_coefficient": 0.004365960272324412,
          "lag_flow_t": 1.2366392078002155,
          "lag_flow_p": 0.21784113647901082,
          "r2": 0.015465962135541522
        },
        "flow_equation": {
          "lag_price_coefficient": 0.28240689510341277,
          "lag_price_t": 0.4147335695887475,
          "lag_price_p": 0.6788335741506197,
          "lag_flow_coefficient": 0.9043957994670934
        },
        "granger_flow_to_price": {
          "F": 1.5292765302687643,
          "p": 0.21784113647900716,
          "df1": 1,
          "df2": 179
        },
        "granger_price_to_flow": {
          "F": 793.2896768232221,
          "p": 1.0994679140166335e-67,
          "df1": 1,
          "df2": 179
        },
        "coefficients": {
          "price_equation": [
            0.0020473162854222657,
            -0.09513558708563634,
            0.004365960272324412
          ],
          "flow_equation": [
            0.002497105938094805,
            0.28240689510341277,
            0.9043957994670934
          ]
        }
      }
    },
    {
      "price_var": "r7",
      "flow_var": "flow",
      "sessions": 189,
      "sessions_in_window": 197,
      "regression_n": 188,
      "first_date": "2024-01-23",
      "last_date": "2024-10-11",
      "contemporaneous": {
        "pearson": 0.5928909038388251,
        "spearman": 0.575472368865426
      },
      "persistence": {
        "ar1": 0.5929803697536973,
        "t": 10.054958867880018,
        "p": 2.860182591743773e-19,
        "n": 188
      },
      "var1": {
        "n": 188,
        "price_equation": {
          "lag_price_coefficient": 0.7253937429276737,
          "lag_price_t": 14.70230536758698,
          "lag_flow_coefficient": 6.294826007599257e-05,
          "lag_flow_t": 3.4709220741817375,
          "lag_flow_p": 0.0006455067625516157,
          "r2": 0.7064974261610992
        },
        "flow_equation": {
          "lag_price_coefficient": 317.96524779420275,
          "lag_price_t": 1.6025118260199134,
          "lag_price_p": 0.11074849764133521,
          "lag_flow_coefficient": 0.5236730331510441
        },
        "granger_flow_to_price": {
          "F": 12.047300045019702,
          "p": 0.0006455067625588762,
          "df1": 1,
          "df2": 185
        },
        "granger_price_to_flow": {
          "F": 51.554026814309175,
          "p": 1.6423191176919596e-11,
          "df1": 1,
          "df2": 185
        },
        "coefficients": {
          "price_equation": [
            -0.001443449400365353,
            0.7253937429276737,
            6.294826007599257e-05
          ],
          "flow_equation": [
            41.69164356568853,
            317.96524779420275,
            0.5236730331510441
          ]
        }
      }
    },
    {
      "price_var": "r7",
      "flow_var": "sum7",
      "sessions": 189,
      "sessions_in_window": 197,
      "regression_n": 188,
      "first_date": "2024-01-23",
      "last_date": "2024-10-11",
      "contemporaneous": {
        "pearson": 0.710042177654701,
        "spearman": 0.695600703887378
      },
      "persistence": {
        "ar1": 0.9552138861890946,
        "t": 44.19792990140278,
        "p": 1.3570705252211758e-100,
        "n": 188
      },
      "var1": {
        "n": 188,
        "price_equation": {
          "lag_price_coefficient": 0.8291624594747604,
          "lag_price_t": 14.226150240756295,
          "lag_flow_coefficient": -2.508561686109209e-07,
          "lag_flow_t": -0.05354698716660054,
          "lag_flow_p": 0.9573538727277127,
          "r2": 0.6873892249262261
        },
        "flow_equation": {
          "lag_price_coefficient": 2086.873050893646,
          "lag_price_t": 5.942008418881746,
          "lag_price_p": 1.3712240429927492e-08,
          "lag_flow_coefficient": 0.8359963120962358
        },
        "granger_flow_to_price": {
          "F": 0.002867279833929133,
          "p": 0.9573538727329012,
          "df1": 1,
          "df2": 185
        },
        "granger_price_to_flow": {
          "F": 877.017335959692,
          "p": 4.027650750460262e-72,
          "df1": 1,
          "df2": 185
        },
        "coefficients": {
          "price_equation": [
            0.00310709633827164,
            0.8291624594747604,
            -2.508561686109209e-07
          ],
          "flow_equation": [
            78.73271033519022,
            2086.873050893646,
            0.8359963120962358
          ]
        }
      }
    },
    {
      "price_var": "r7",
      "flow_var": "nd",
      "sessions": 183,
      "sessions_in_window": 197,
      "regression_n": 182,
      "first_date": "2024-01-31",
      "last_date": "2024-10-11",
      "contemporaneous": {
        "pearson": 0.46728144344421446,
        "spearman": 0.47051647568397403
      },
      "persistence": {
        "ar1": 0.9059691614002573,
        "t": 28.478972982047154,
        "p": 1.3885004103620035e-68,
        "n": 182
      },
      "var1": {
        "n": 182,
        "price_equation": {
          "lag_price_coefficient": 0.8122361614455248,
          "lag_price_t": 17.266352288253163,
          "lag_flow_coefficient": 0.004184863466584393,
          "lag_flow_t": 0.7675177734204064,
          "lag_flow_p": 0.44378495812918173,
          "r2": 0.690195149120507
        },
        "flow_equation": {
          "lag_price_coefficient": 0.3764007055806019,
          "lag_price_t": 1.2129719312706402,
          "lag_price_p": 0.2267388619951365,
          "lag_flow_coefficient": 0.8855165477277585
        },
        "granger_flow_to_price": {
          "F": 0.5890835325162156,
          "p": 0.44378495812918173,
          "df1": 1,
          "df2": 179
        },
        "granger_price_to_flow": {
          "F": 606.1383312801587,
          "p": 2.3070211255241623e-59,
          "df1": 1,
          "df2": 179
        },
        "coefficients": {
          "price_equation": [
            0.0024225680304904517,
            0.8122361614455248,
            0.004184863466584393
          ],
          "flow_equation": [
            -0.001718889546723856,
            0.3764007055806019,
            0.8855165477277585
          ]
        }
      }
    }
  ],
  "partition_stability": {
    "r1+flow": {
      "EARLY": {
        "sessions": 64,
        "first_date": "2024-01-15",
        "last_date": "2024-04-11",
        "lag_flow_coefficient": 1.6889314084577174e-05,
        "lag_flow_p": 0.34212982371064105,
        "granger_F": 0.9169114793637941,
        "granger_p": 0.3421298237104292,
        "contemporaneous_pearson": 0.2769881120627767
      },
      "MIDDLE": {
        "sessions": 64,
        "first_date": "2024-04-15",
        "last_date": "2024-07-11",
        "lag_flow_coefficient": 2.8161656219503955e-05,
        "lag_flow_p": 0.1520174151251399,
        "granger_F": 2.1050963015779365,
        "granger_p": 0.15201741512509137,
        "contemporaneous_pearson": 0.4855633535192357
      },
      "LATE": {
        "sessions": 65,
        "first_date": "2024-07-15",
        "last_date": "2024-10-11",
        "lag_flow_coefficient": -4.6865174637649735e-06,
        "lag_flow_p": 0.8750234988952832,
        "granger_F": 0.024945952020146937,
        "granger_p": 0.8750234988952497,
        "contemporaneous_pearson": 0.5397980881980147
      }
    },
    "r1+sum7": {
      "EARLY": {
        "sessions": 62,
        "first_date": "2024-01-22",
        "last_date": "2024-04-16",
        "lag_flow_coefficient": -1.7268617506053534e-06,
        "lag_flow_p": 0.6745694477439945,
        "granger_F": 0.17810228400352307,
        "granger_p": 0.6745694477438662,
        "contemporaneous_pearson": 0.023708413457351786
      },
      "MIDDLE": {
        "sessions": 62,
        "first_date": "2024-04-18",
        "last_date": "2024-07-12",
        "lag_flow_coefficient": -4.4103062110549404e-07,
        "lag_flow_p": 0.9158347447725286,
        "granger_F": 0.011266448642453032,
        "granger_p": 0.9158347447724327,
        "contemporaneous_pearson": 0.07742355684900032
      },
      "LATE": {
        "sessions": 64,
        "first_date": "2024-07-16",
        "last_date": "2024-10-11",
        "lag_flow_coefficient": -4.570575339250458e-06,
        "lag_flow_p": 0.4634724667221667,
        "granger_F": 0.5444451894055597,
        "granger_p": 0.4634724667223855,
        "contemporaneous_pearson": 0.05400531948537144
      }
    },
    "r1+nd": {
      "EARLY": {
        "sessions": 60,
        "first_date": "2024-01-31",
        "last_date": "2024-04-23",
        "lag_flow_coefficient": 0.002269444639034762,
        "lag_flow_p": 0.7780981672938025,
        "granger_F": 0.08017970341871558,
        "granger_p": 0.7780981672937943,
        "contemporaneous_pearson": 0.019810342271246534
      },
      "MIDDLE": {
        "sessions": 60,
        "first_date": "2024-04-25",
        "last_date": "2024-07-17",
        "lag_flow_coefficient": 0.004984871742773208,
        "lag_flow_p": 0.3923027309585829,
        "granger_F": 0.7432370762402083,
        "granger_p": 0.3923027309585829,
        "contemporaneous_pearson": 0.19435386883776404
      },
      "LATE": {
        "sessions": 61,
        "first_date": "2024-07-19",
        "last_date": "2024-10-11",
        "lag_flow_coefficient": 0.004734833573372798,
        "lag_flow_p": 0.39711288135594347,
        "granger_F": 0.7279710887030075,
        "granger_p": 0.39711288135594347,
        "contemporaneous_pearson": 0.14174115125270795
      }
    },
    "r7+flow": {
      "EARLY": {
        "sessions": 62,
        "first_date": "2024-01-23",
        "last_date": "2024-04-17",
        "lag_flow_coefficient": 5.627859869891873e-05,
        "lag_flow_p": 0.0767951734769408,
        "granger_F": 3.246021377294752,
        "granger_p": 0.07679517347683969,
        "contemporaneous_pearson": 0.6433139002736648
      },
      "MIDDLE": {
        "sessions": 62,
        "first_date": "2024-04-19",
        "last_date": "2024-07-15",
        "lag_flow_coefficient": 6.285638646119419e-05,
        "lag_flow_p": 0.027704776445421693,
        "granger_F": 5.099884734085655,
        "granger_p": 0.027704776445721113,
        "contemporaneous_pearson": 0.41621559096261473
      },
      "LATE": {
        "sessions": 63,
        "first_date": "2024-07-17",
        "last_date": "2024-10-11",
        "lag_flow_coefficient": 6.866529728359967e-05,
        "lag_flow_p": 0.1252878398639461,
        "granger_F": 2.4181098521718862,
        "granger_p": 0.12528783986302705,
        "contemporaneous_pearson": 0.5547177547482455
      }
    },
    "r7+sum7": {
      "EARLY": {
        "sessions": 62,
        "first_date": "2024-01-23",
        "last_date": "2024-04-17",
        "lag_flow_coefficient": -6.584596310372116e-06,
        "lag_flow_p": 0.393863992637312,
        "granger_F": 0.7379214341324022,
        "granger_p": 0.3938639926402666,
        "contemporaneous_pearson": 0.6900766946773881
      },
      "MIDDLE": {
        "sessions": 62,
        "first_date": "2024-04-19",
        "last_date": "2024-07-15",
        "lag_flow_coefficient": 7.34044337599623e-06,
        "lag_flow_p": 0.36982345643080217,
        "granger_F": 0.8169117825530767,
        "granger_p": 0.369823456436265,
        "contemporaneous_pearson": 0.6337671099452084
      },
      "LATE": {
        "sessions": 63,
        "first_date": "2024-07-17",
        "last_date": "2024-10-11",
        "lag_flow_coefficient": -9.949043219430926e-06,
        "lag_flow_p": 0.4299818518130719,
        "granger_F": 0.6315244069449416,
        "granger_p": 0.42998185180584625,
        "contemporaneous_pearson": 0.7036853737065853
      }
    },
    "r7+nd": {
      "EARLY": {
        "sessions": 60,
        "first_date": "2024-01-31",
        "last_date": "2024-04-23",
        "lag_flow_coefficient": -0.004016672098747602,
        "lag_flow_p": 0.7454633587538083,
        "granger_F": 0.10642865059806784,
        "granger_p": 0.7454633587537725,
        "contemporaneous_pearson": 0.46936465799406957
      },
      "MIDDLE": {
        "sessions": 60,
        "first_date": "2024-04-25",
        "last_date": "2024-07-17",
        "lag_flow_coefficient": 0.011949095800139522,
        "lag_flow_p": 0.17437336895724143,
        "granger_F": 1.8927190258668543,
        "granger_p": 0.17437336895724398,
        "contemporaneous_pearson": 0.416616382951646
      },
      "LATE": {
        "sessions": 61,
        "first_date": "2024-07-19",
        "last_date": "2024-10-11",
        "lag_flow_coefficient": 0.014633104473770342,
        "lag_flow_p": 0.1603685310849411,
        "granger_F": 2.0231354805047532,
        "granger_p": 0.16036853108494353,
        "contemporaneous_pearson": 0.685337902308428
      }
    }
  },
  "irf": {
    "r1+sum7": {
      "horizon": 10,
      "shock": "one Cholesky standard deviation of the flow innovation",
      "ordering": [
        "flow",
        "price"
      ],
      "shock_size_usd_m": 292.45276665019196,
      "flow_response_point_usd_m": [
        292.45276665019196,
        309.2250059884969,
        290.4553379396392,
        275.56342568144294,
        261.2037825969036,
        247.61175665570224,
        234.72538879477972,
        222.50979683136683,
        210.92991806805836,
        199.9526815478913
      ],
      "price_response_point_log_return": [
        0.011392194134082082,
        -0.000698689497572424,
        0.00029977122137716405,
        0.00020366653478403406,
        0.00019980349322601466,
        0.00018884164617330877,
        0.00017906109354068933,
        0.00016973843115536714,
        0.00016090521639787367,
        0.00015253134286423813
      ],
      "price_response_point_bps": [
        113.92194134082082,
        -6.98689497572424,
        2.9977122137716403,
        2.0366653478403407,
        1.9980349322601467,
        1.8884164617330876,
        1.7906109354068933,
        1.6973843115536713,
        1.6090521639787367,
        1.5253134286423813
      ],
      "price_response_ci95_low_bps": [
        72.6827445774654,
        -10.656482108253329,
        2.4909669169789144,
        1.7331997470355667,
        1.7106553186962454,
        1.616853001406151,
        1.5330771925046636,
        1.4532617862327444,
        1.3776335670781537,
        1.3059384026331062
      ],
      "price_response_ci95_high_bps": [
        158.516392827842,
        -3.5465450496544877,
        3.4818266394467483,
        2.3656745498570584,
        2.314920581335678,
        2.1896850254559386,
        2.0761276912161257,
        1.9680482963800936,
        1.8656297135108546,
        1.768538185683082
      ],
      "draws": 1000,
      "seed": 20261007
    },
    "r1+nd": {
      "horizon": 10,
      "shock": "one Cholesky standard deviation of the flow innovation",
      "ordering": [
        "flow",
        "price"
      ],
      "shock_size_usd_m": 0.31166757729616146,
      "flow_response_point_usd_m": [
        0.31166757729616146,
        0.2828125377728989,
        0.2560691620071641,
        0.23190854034413,
        0.21002233047376248,
        0.1902021167959061,
        0.17225232683681407,
        0.15599650247794355,
        0.141274774948677,
        0.12794236874861695
      ],
      "price_response_point_log_return": [
        0.003334515029527614,
        0.0010434972156666512,
        0.00113547458419705,
        0.001009963747102277,
        0.0009164199799394304,
        0.000829764998340891,
        0.000751474705382661,
        0.0006805548285083853,
        0.0006163295492861485,
        0.0005581651813979325
      ],
      "price_response_point_bps": [
        33.34515029527614,
        10.434972156666513,
        11.3547458419705,
        10.09963747102277,
        9.164199799394304,
        8.29764998340891,
        7.514747053826611,
        6.8055482850838525,
        6.163295492861485,
        5.581651813979325
      ],
      "price_response_ci95_low_bps": [
        -7.907666941456224,
        4.009267144564726,
        9.02506277736815,
        7.825050568165439,
        7.129525732873314,
        6.453451543735881,
        5.844738110780479,
        5.293127389049597,
        4.793606408455058,
        4.34122311932253
      ],
      "price_response_ci95_high_bps": [
        78.59823360241805,
        16.153854745412605,
        13.553654697224577,
        12.18293308971826,
        11.030829309247729,
        9.98817379259694,
        9.045727446124781,
        8.192047229448129,
        7.418947485035924,
        6.7188052151541
      ],
      "draws": 1000,
      "seed": 20261007
    }
  },
  "falsification_reference_combos": {
    "r1+sum7": {
      "sessions": 190,
      "variants": {
        "none": {
          "rows": 189,
          "lag_flow_coefficient": 7.853013694592047e-07,
          "lag_flow_t": 0.32661445943675804,
          "lag_flow_p": 0.7443267370024464,
          "lag_price_coefficient": -0.08149027700906346,
          "degenerate": false,
          "condition_number": 36133.90881541141,
          "r2": 0.006860910540315568,
          "usable_as_evidence": true
        },
        "same_day_return": {
          "rows": 189,
          "lag_flow_coefficient": -1.2465082156198138e-18,
          "lag_flow_t": -11.256742851997473,
          "lag_flow_p": 1.0018394434054756e-22,
          "lag_price_coefficient": -1.2641119704823178e-17,
          "degenerate": true,
          "condition_number": 37674.96852035663,
          "r2": 1.0,
          "usable_as_evidence": false
        },
        "previous_return": {
          "rows": 189,
          "lag_flow_coefficient": 7.853013694790614e-07,
          "lag_flow_t": 0.32573528030129806,
          "lag_flow_p": 0.7449927847089185,
          "lag_price_coefficient": -0.04074513850454371,
          "degenerate": true,
          "condition_number": 8.48761081711966e+19,
          "r2": 0.006860910540315457,
          "usable_as_evidence": false
        },
        "realised_vol_20": {
          "rows": 177,
          "lag_flow_coefficient": 1.0983764022218156e-06,
          "lag_flow_t": 0.44036950316397994,
          "lag_flow_p": 0.6602192360295243,
          "lag_price_coefficient": -0.0882144571910383,
          "degenerate": false,
          "condition_number": 136165.25834504864,
          "r2": 0.008209772709543928,
          "usable_as_evidence": true
        },
        "day_of_week": {
          "rows": 189,
          "lag_flow_coefficient": 7.917923655771537e-07,
          "lag_flow_t": 0.3319856010561575,
          "lag_flow_p": 0.7402821417274629,
          "lag_price_coefficient": -0.06649626530626374,
          "degenerate": false,
          "condition_number": 36801.05709484557,
          "r2": 0.04496346730330336,
          "usable_as_evidence": true
        },
        "all_controls": {
          "rows": 177,
          "lag_flow_coefficient": -2.86015362687084e-19,
          "lag_flow_t": -10.604605614828294,
          "lag_flow_p": 2.057293129974491e-20,
          "lag_price_coefficient": 2.221549309664112e-15,
          "degenerate": true,
          "condition_number": 6.615160636431571e+19,
          "r2": 1.0,
          "usable_as_evidence": false
        },
        "post_hoc_trailing_5_return": {
          "rows": 185,
          "lag_flow_coefficient": -6.066483181952674e-06,
          "lag_flow_t": -2.7336006681460168,
          "lag_flow_p": 0.006886613101119957,
          "lag_price_coefficient": -0.3249084668931293,
          "degenerate": false,
          "condition_number": 41104.45724019601,
          "r2": 0.28890464029091745,
          "usable_as_evidence": true
        },
        "post_hoc_trailing_20_return": {
          "rows": 170,
          "lag_flow_coefficient": -1.1468084940381637e-05,
          "lag_flow_t": -3.2024470566906698,
          "lag_flow_p": 0.0016335413085349305,
          "lag_price_coefficient": -0.15756300174712706,
          "degenerate": false,
          "condition_number": 35744.27076077586,
          "r2": 0.12107769801413215,
          "usable_as_evidence": true
        },
        "winsorised_1_99": {
          "lag_price_coefficient": -0.10542725111967723,
          "lag_price_t": -1.417719383869748,
          "lag_flow_coefficient": 1.978657800635735e-06,
          "lag_flow_t": 0.7445590670260384,
          "lag_flow_p": 0.4575092784681154,
          "r2": 0.012796816143657241
        },
        "exclude_abs_flow_gt_10bn": {
          "lag_price_coefficient": -0.08149027700906346,
          "lag_price_t": -1.1135551613776193,
          "lag_flow_coefficient": 7.853013694592047e-07,
          "lag_flow_t": 0.32661445943675804,
          "lag_flow_p": 0.7443267370024464,
          "r2": 0.006860910540315568
        },
        "exclude_first_20_sessions": {
          "lag_price_coefficient": -0.10244308557214207,
          "lag_price_t": -1.3125439589936647,
          "lag_flow_coefficient": 5.572573360781713e-07,
          "lag_flow_t": 0.2076189907266657,
          "lag_flow_p": 0.8357825040750608,
          "r2": 0.010368695838861908
        }
      },
      "winsorised_variant_note": "the 1/99 winsorised variant is implemented by excluding the trimmed rows, which is equivalent to trimming for an OLS estimate",
      "degenerate_specifications": {
        "specs": [
          "all_controls",
          "previous_return",
          "same_day_return"
        ],
        "why": {
          "all_controls": "contains the same-session return, so it inherits that exact fit and absorbs the whole equation.",
          "previous_return": "the control is the previous 1-session return, which is exactly the AR(1) term already in the price equation whenever the price variable is that same 1-session return; the duplicated column makes the design singular, so this control is only identifiable in the 7-session-return combinations. The momentum question is therefore answered by the AR(1) term itself in the daily-return specifications, not by this redundant control.",
          "same_day_return": "adding the same-session return as a regressor when the dependent variable IS that same return makes the fit exact; the coefficient collapses to ~0 with a meaningless t-statistic. A valid same-session control would need an exogenous instrument, which the spec does not declare."
        }
      },
      "degenerate_flags_match_declaration": true,
      "post_hoc_note": "post_hoc_trailing_5_return and post_hoc_trailing_20_return were NOT part of the frozen battery; they are reported as explicitly post-hoc exploratory controls"
    },
    "r1+nd": {
      "sessions": 183,
      "variants": {
        "none": {
          "rows": 182,
          "lag_flow_coefficient": 0.004365960272324412,
          "lag_flow_t": 1.2366392078002155,
          "lag_flow_p": 0.21784113647901082,
          "lag_price_coefficient": -0.09513558708563634,
          "degenerate": false,
          "condition_number": 29.407600267951437,
          "r2": 0.015465962135541522,
          "usable_as_evidence": true
        },
        "same_day_return": {
          "rows": 182,
          "lag_flow_coefficient": 1.3985361651046688e-17,
          "lag_flow_t": 5.852484091731423,
          "lag_flow_p": 2.2808911720354045e-08,
          "lag_price_coefficient": 5.204170427930421e-16,
          "degenerate": true,
          "condition_number": 30.813264838772703,
          "r2": 1.0,
          "usable_as_evidence": false
        },
        "previous_return": {
          "rows": 182,
          "lag_flow_coefficient": 0.004365960272324411,
          "lag_flow_t": 1.2331800703731657,
          "lag_flow_p": 0.21913464153607454,
          "lag_price_coefficient": -0.047567793542817885,
          "degenerate": true,
          "condition_number": 6.056966475117081e+16,
          "r2": 0.015465962135541522,
          "usable_as_evidence": false
        },
        "realised_vol_20": {
          "rows": 177,
          "lag_flow_coefficient": 0.004320446635917382,
          "lag_flow_t": 1.1850608058247212,
          "lag_flow_p": 0.23761874866087052,
          "lag_price_coefficient": -0.09511090890466575,
          "degenerate": false,
          "condition_number": 108.17639078694937,
          "r2": 0.015093237565914519,
          "usable_as_evidence": true
        },
        "day_of_week": {
          "rows": 182,
          "lag_flow_coefficient": 0.004209140603915009,
          "lag_flow_t": 1.200485746546205,
          "lag_flow_p": 0.23157323663075013,
          "lag_price_coefficient": -0.07487483854422981,
          "degenerate": false,
          "condition_number": 32.37598262586456,
          "r2": 0.05101753622204652,
          "usable_as_evidence": true
        },
        "all_controls": {
          "rows": 177,
          "lag_flow_coefficient": -6.0460341730472056e-18,
          "lag_flow_t": -0.8310690463452798,
          "lag_flow_p": 0.4071212591947173,
          "lag_price_coefficient": -1.5785983631388945e-16,
          "degenerate": true,
          "condition_number": 1.022101948166771e+17,
          "r2": 1.0,
          "usable_as_evidence": false
        },
        "post_hoc_trailing_5_return": {
          "rows": 178,
          "lag_flow_coefficient": -0.0016008158396642474,
          "lag_flow_t": -0.4953215783775226,
          "lag_flow_p": 0.6209980911974307,
          "lag_price_coefficient": -0.31780625717068056,
          "degenerate": false,
          "condition_number": 32.56792182289382,
          "r2": 0.2635683931745868,
          "usable_as_evidence": true
        },
        "post_hoc_trailing_20_return": {
          "rows": 163,
          "lag_flow_coefficient": 0.0047461646945418864,
          "lag_flow_t": 1.3057185561374005,
          "lag_flow_p": 0.19353433227503158,
          "lag_price_coefficient": -0.1689340085141915,
          "degenerate": false,
          "condition_number": 29.127632075992707,
          "r2": 0.07694378508541988,
          "usable_as_evidence": true
        },
        "winsorised_1_99": {
          "lag_price_coefficient": -0.09513558708563634,
          "lag_price_t": -1.2706992207071421,
          "lag_flow_coefficient": 0.004365960272324412,
          "lag_flow_t": 1.2366392078002155,
          "lag_flow_p": 0.21784113647901082,
          "r2": 0.015465962135541522
        },
        "exclude_abs_flow_gt_10bn": {
          "lag_price_coefficient": -0.09513558708563634,
          "lag_price_t": -1.2706992207071421,
          "lag_flow_coefficient": 0.004365960272324412,
          "lag_flow_t": 1.2366392078002155,
          "lag_flow_p": 0.21784113647901082,
          "r2": 0.015465962135541522
        },
        "exclude_first_20_sessions": {
          "lag_price_coefficient": -0.1443170888253797,
          "lag_price_t": -1.822471397153487,
          "lag_flow_coefficient": 0.004334958607180518,
          "lag_flow_t": 1.1845465257373178,
          "lag_flow_p": 0.23797558413429643,
          "r2": 0.02642735737098978
        }
      },
      "winsorised_variant_note": "the 1/99 winsorised variant is implemented by excluding the trimmed rows, which is equivalent to trimming for an OLS estimate",
      "degenerate_specifications": {
        "specs": [
          "all_controls",
          "previous_return",
          "same_day_return"
        ],
        "why": {
          "all_controls": "contains the same-session return, so it inherits that exact fit and absorbs the whole equation.",
          "previous_return": "the control is the previous 1-session return, which is exactly the AR(1) term already in the price equation whenever the price variable is that same 1-session return; the duplicated column makes the design singular, so this control is only identifiable in the 7-session-return combinations. The momentum question is therefore answered by the AR(1) term itself in the daily-return specifications, not by this redundant control.",
          "same_day_return": "adding the same-session return as a regressor when the dependent variable IS that same return makes the fit exact; the coefficient collapses to ~0 with a meaningless t-statistic. A valid same-session control would need an exogenous instrument, which the spec does not declare."
        }
      },
      "degenerate_flags_match_declaration": true,
      "post_hoc_note": "post_hoc_trailing_5_return and post_hoc_trailing_20_return were NOT part of the frozen battery; they are reported as explicitly post-hoc exploratory controls"
    },
    "r1+flow": {
      "sessions": 195,
      "variants": {
        "none": {
          "rows": 194,
          "lag_flow_coefficient": 2.342561165094671e-05,
          "lag_flow_t": 2.0033135176913004,
          "lag_flow_p": 0.046557236280923404,
          "lag_price_coefficient": -0.14475151978688047,
          "degenerate": false,
          "condition_number": 7930.946443178702,
          "r2": 0.02684846747785563,
          "usable_as_evidence": true
        },
        "same_day_return": {
          "rows": 194,
          "lag_flow_coefficient": -1.0220457124970736e-17,
          "lag_flow_t": -4.639387804448548,
          "lag_flow_p": 6.494780492019951e-06,
          "lag_price_coefficient": -4.5245111910535707e-17,
          "degenerate": true,
          "condition_number": 8253.06067336853,
          "r2": 1.0,
          "usable_as_evidence": false
        },
        "previous_return": {
          "rows": 194,
          "lag_flow_coefficient": 2.3425611650936365e-05,
          "lag_flow_t": 1.9980623592022124,
          "lag_flow_p": 0.04713609473691169,
          "lag_price_coefficient": -0.07237575989343556,
          "degenerate": true,
          "condition_number": 4.125043842035258e+19,
          "r2": 0.026848467477855742,
          "usable_as_evidence": false
        },
        "realised_vol_20": {
          "rows": 177,
          "lag_flow_coefficient": 2.8353382691054326e-05,
          "lag_flow_t": 2.2978871361822146,
          "lag_flow_p": 0.022765202883861538,
          "lag_price_coefficient": -0.16405619673688743,
          "degenerate": false,
          "condition_number": 27134.569086567968,
          "r2": 0.03650567835961538,
          "usable_as_evidence": true
        },
        "day_of_week": {
          "rows": 194,
          "lag_flow_coefficient": 2.3098132176123892e-05,
          "lag_flow_t": 1.968476037948898,
          "lag_flow_p": 0.050491121894991026,
          "lag_price_coefficient": -0.1330182462465918,
          "degenerate": false,
          "condition_number": 8109.688836616504,
          "r2": 0.05674656574229131,
          "usable_as_evidence": true
        },
        "all_controls": {
          "rows": 177,
          "lag_flow_coefficient": 2.333180647855961e-19,
          "lag_flow_t": 4.421273275115662,
          "lag_flow_p": 1.7617168005327147e-05,
          "lag_price_coefficient": -1.8222355319553324e-15,
          "degenerate": true,
          "condition_number": 6.459909964092253e+18,
          "r2": 1.0,
          "usable_as_evidence": false
        },
        "post_hoc_trailing_5_return": {
          "rows": 190,
          "lag_flow_coefficient": -1.7768677170933087e-05,
          "lag_flow_t": -1.5084999260214982,
          "lag_flow_p": 0.13312334134652204,
          "lag_price_coefficient": -0.2907776924441565,
          "degenerate": false,
          "condition_number": 8250.60922257879,
          "r2": 0.2683772101465747,
          "usable_as_evidence": true
        },
        "post_hoc_trailing_20_return": {
          "rows": 175,
          "lag_flow_coefficient": 1.2138355679429197e-05,
          "lag_flow_t": 0.9034756827286858,
          "lag_flow_p": 0.36754447076807883,
          "lag_price_coefficient": -0.16687381440674715,
          "degenerate": false,
          "condition_number": 7908.432778538367,
          "r2": 0.073548751612461,
          "usable_as_evidence": true
        },
        "winsorised_1_99": {
          "lag_price_coefficient": -0.153400361462583,
          "lag_price_t": -1.8651191945510701,
          "lag_flow_coefficient": 3.0203903248882487e-05,
          "lag_flow_t": 2.1863570763045397,
          "lag_flow_p": 0.03005847858474639,
          "r2": 0.03027714266751169
        },
        "exclude_abs_flow_gt_10bn": {
          "lag_price_coefficient": -0.14475151978688047,
          "lag_price_t": -1.8445436948057892,
          "lag_flow_coefficient": 2.342561165094671e-05,
          "lag_flow_t": 2.0033135176913004,
          "lag_flow_p": 0.046557236280923404,
          "r2": 0.02684846747785563
        },
        "exclude_first_20_sessions": {
          "lag_price_coefficient": -0.16865307426281248,
          "lag_price_t": -2.04090735292308,
          "lag_flow_coefficient": 2.5252251365081552e-05,
          "lag_flow_t": 2.0187945133138347,
          "lag_flow_p": 0.045080086270844304,
          "r2": 0.03339206304401865
        }
      },
      "winsorised_variant_note": "the 1/99 winsorised variant is implemented by excluding the trimmed rows, which is equivalent to trimming for an OLS estimate",
      "degenerate_specifications": {
        "specs": [
          "all_controls",
          "previous_return",
          "same_day_return"
        ],
        "why": {
          "all_controls": "contains the same-session return, so it inherits that exact fit and absorbs the whole equation.",
          "previous_return": "the control is the previous 1-session return, which is exactly the AR(1) term already in the price equation whenever the price variable is that same 1-session return; the duplicated column makes the design singular, so this control is only identifiable in the 7-session-return combinations. The momentum question is therefore answered by the AR(1) term itself in the daily-return specifications, not by this redundant control.",
          "same_day_return": "adding the same-session return as a regressor when the dependent variable IS that same return makes the fit exact; the coefficient collapses to ~0 with a meaningless t-statistic. A valid same-session control would need an exogenous instrument, which the spec does not declare."
        }
      },
      "degenerate_flags_match_declaration": true,
      "post_hoc_note": "post_hoc_trailing_5_return and post_hoc_trailing_20_return were NOT part of the frozen battery; they are reported as explicitly post-hoc exploratory controls"
    }
  },
  "economic_magnitude": {
    "sessions": 195,
    "flow_sd_usd_m": 227.59582845428247,
    "one_sd_shock_usd_m": 227.59582845428247,
    "coefficient_flow_to_price": 2.342561165094671e-05,
    "coefficient_flow_persistence": 0.485450295847931,
    "cumulative_bps_per_1sd_shock_h1_h2_h3": [
      53.31571490745508,
      18.16459881378985,
      11.70936382681298
    ],
    "cumulative_bps_per_500m_shock_h1_h2_h3": [
      117.12805825473355,
      39.905386089795144,
      25.724029975279315
    ],
    "cost_floor_bps_round_trip": 23.791,
    "interpretation": "a scale comparison only: these are predicted returns associated with a flow shock in the estimated VAR, before any strategy, turnover or execution assumption"
  },
  "flow_series_stats": {
    "mean_usd_m": 82.34082503556186,
    "sd_usd_m": 336.02272015318755,
    "min_usd_m": -1113.7,
    "max_usd_m": 1373.8,
    "zero_days": 17,
    "cumulative_usd_m": 57885.59999999999
  }
}
```
