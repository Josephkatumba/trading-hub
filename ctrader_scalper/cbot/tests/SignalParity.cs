// Parity harness: runs the cBot's SignalCore on bars exported by the Python
// engine and writes every candidate, so tests/test_parity.py can diff them.
// Usage: SignalParity.exe <m5.csv> <m15.csv> <m1.csv> <crypto 0|1> <out.csv>
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using cAlgo.Robots;

public static class SignalParity
{
    static BarSeries Load(string path, out double[] spread)
    {
        string[] lines = System.IO.File.ReadAllLines(path);
        var s = new BarSeries(lines.Length - 1);
        spread = new double[lines.Length - 1];
        string[] head = lines[0].Split(',');
        int it = Array.IndexOf(head, "time"), io = Array.IndexOf(head, "open"), ih = Array.IndexOf(head, "high"),
            il = Array.IndexOf(head, "low"), ic = Array.IndexOf(head, "close"), isp = Array.IndexOf(head, "spread_px");
        for (int i = 1; i < lines.Length; i++)
        {
            string[] f = lines[i].Split(',');
            s.T[i - 1] = DateTime.Parse(f[it], CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal);
            s.O[i - 1] = double.Parse(f[io], CultureInfo.InvariantCulture);
            s.H[i - 1] = double.Parse(f[ih], CultureInfo.InvariantCulture);
            s.L[i - 1] = double.Parse(f[il], CultureInfo.InvariantCulture);
            s.C[i - 1] = double.Parse(f[ic], CultureInfo.InvariantCulture);
            spread[i - 1] = isp >= 0 ? double.Parse(f[isp], CultureInfo.InvariantCulture) : double.NaN;
        }
        return s;
    }

    public static int Main(string[] a)
    {
        double[] sp, dummy;
        BarSeries m5 = Load(a[0], out sp);
        BarSeries m15 = Load(a[1], out dummy);
        BarSeries m1 = Load(a[2], out dummy);
        bool crypto = a[3] == "1";
        var ind = new SignalCore.M5Indicators(m5);
        var tf = new SignalCore.HigherTf(m15, m1);
        var st = new SignalState();
        using (var w = new StreamWriter(a[4]))
        {
            w.WriteLine("time,side,setup,anchor,atr,rsi,score");
            for (int i = 0; i < m5.Count; i++)
            {
                foreach (Candidate c in SignalCore.Step(st, m5, ind, tf, i, sp[i], crypto))
                {
                    w.WriteLine(string.Format(CultureInfo.InvariantCulture, "{0:yyyy-MM-dd HH:mm:ss},{1},{2},{3:R},{4:R},{5:R},{6}",
                        c.Time, c.Side, c.Setup, c.Anchor, c.Atr, c.Rsi, c.Score));
                }
            }
        }
        return 0;
    }
}
