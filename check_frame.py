from open_iris_client import OpenIrisClient

if __name__ == "__main__":
    onAt=0
    nFrames=0
    with OpenIrisClient() as client:
        while True:
            data = client.fetch_next_data(True)
            if data is not None:
                if not onAt and data.extra.ints[0]&0x1:
                    onAt = data.left.frame_number
                    offAt = 0
                elif onAt and not data.extra.ints[0]&0x1:
                    print(f"onoff {data.left.frame_number} diff {data.left.frame_number-onAt}")
                    onAt = 0
