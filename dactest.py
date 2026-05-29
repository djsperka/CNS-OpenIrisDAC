import AIOUSB as ao

# Configure both ports (USB-AO16-8E has two ports, each with 8 bits, I think)
status=ao.DIO_Configure(ao.diOnly, False, [0,0],[0,0])
if not status:
    raise RuntimeError("DIO_Configure failed with status {status}")

# read first bit on first port
def getbit():
    status,v=ao.DIO_Read8(ao.diOnly,0)
    return v&0x1
