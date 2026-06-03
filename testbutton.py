from AIOUSB import DIO_Configure, DIO_Read8, diOnly
import time

if __name__ == "__main__":

    DIO_Configure(diOnly, False, [0,0], [0,0])

    oldstatus = -1
    for i in range(30000):
        status, v = DIO_Read8(diOnly, 0)
        gDown = v&0x1
        rDown = v&0x2
        print(f"{gDown},{rDown}")
        time.sleep(.01)


