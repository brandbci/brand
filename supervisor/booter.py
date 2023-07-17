from brand import Booter

if __name__ == '__main__':
    # parse command line arguments
    args = Booter.parse_booter_args()
    kwargs = vars(args)
    # Run Booter
    booter = Booter(**kwargs)
    booter.run()
