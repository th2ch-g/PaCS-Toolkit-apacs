import subprocess
from pathlib import Path

# import pacs_ta.utils.genrepresent as genrepresent
import pacs_ta.utils.rmfile as rmfile
import pacs_ta.utils.rmmol as rmmol
from pacs_ta._version import __version__
from pacs_ta.mdrun.analyzer.superAnalyzer import SuperAnalyzer
from pacs_ta.mdrun.exporter.superExporter import SuperExporter
from pacs_ta.mdrun.simulator.superSimulator import SuperSimulator
from pacs_ta.models.settings import MDsettings
from pacs_ta.utils.logger import close_logger, generate_logger

LOGGER = generate_logger(__name__)


class Cycle:
    """
    class for running a cycle of pacs_tamd

    @param
    settings:MDsettings MD settings
    cycle:int cycle number
    """

    def __init__(
        self,
        cycle: int,
        settings: MDsettings,
        simulator: SuperSimulator,
        analyzer: SuperAnalyzer,
        exporter: SuperExporter,
    ) -> None:
        self.cycle = cycle
        self.settings = settings
        self.simulator = simulator
        self.analyzer = analyzer
        self.exporter = exporter

    def run(self) -> None:
        if not self.is_needed():
            LOGGER.info(f"cycle{self.cycle:03} was skipped")
            return
        if self.cycle == 0:
            self.prepare_trial()
        else:
            self.run_md()
            self.calculate_cv()

    def is_finished(self) -> bool:
        if not self.is_needed():
            return False
        if self.meet_threshold():
            if self.settings.rmmol:
                self.rmmol(last_cycle=True)
            if self.settings.rmfile:
                self.clean_cycle()
            return True
        else:
            self.prepare_next_cycle()
            self.export()
            if self.settings.rmmol:
                self.rmmol(last_cycle=False)
            if self.settings.rmfile:
                self.clean_cycle()
            return False

    def prepare_trial(self) -> None:
        """
        this is a method for preparing the trial, cycle 0
        """
        self.prepare_next_cycle(cycle=-1, replica=1)
        extension = Path(self.settings.structure).suffix
        dir = self.settings.each_replica(_cycle=0, _replica=1)
        cmd_cp = f"cp {self.settings.structure} {dir}/input{extension}"
        res_cp = subprocess.run(cmd_cp, shell=True)
        if res_cp.returncode != 0:
            LOGGER.error("error occurred at cp command")
            LOGGER.error(f"check the authority of {dir}/")
            exit(1)
        tmp = self.settings.n_replica
        self.settings.n_replica = 1
        # # create version file of pacs_tatk
        # version_file = f"{self.settings.each_trial()}/pacs_tatk.version"
        # if Path(version_file).exists():
        #     with open(version_file) as f:
        #         line = f.readline().strip()
        #         if __version__ != line:
        #             LOGGER.error("PaCS-Toolkit version error")
        #             LOGGER.error(
        #                 f"Version used in {self.settings.each_trial()} is {line},"
        #             )
        #             LOGGER.error(f"But you're using PaCS-Toolkit {__version__}")
        #             exit(1)
        # else:
        #     with open(version_file, "w") as f:
        #         f.write(f"{__version__}")
        self.run_md()
        self.calculate_cv()
        self.settings.n_replica = tmp
        # If rmmol is True, create a topology file with keep_selection only
        if self.settings.rmmol:
            rmmol.make_top(self.settings)

    def prepare_next_cycle(self, cycle=None, replica=None) -> None:
        if cycle is None:
            cycle = self.cycle
        if replica is None:
            replica = self.settings.n_replica

        def make_dir(path: Path) -> None:
            if not path.exists():
                path.mkdir(parents=True)

        next_cycle_dir = Path(f"{self.settings.each_cycle(_cycle=cycle + 1)}")
        make_dir(next_cycle_dir / "summary")
        for rep in range(1, replica + 1):
            make_dir(next_cycle_dir / f"replica{rep:03}")

        cmd_touch = f"touch {next_cycle_dir}/summary/progress.log"
        res_touch = subprocess.run(cmd_touch, shell=True)
        if res_touch.returncode != 0:
            LOGGER.error("error occurred at touch command")
            LOGGER.error(f"check authority of {next_cycle_dir}/summary/")
            exit(1)

    def run_md(self) -> None:
        self.simulator.run_parallel(self.settings, self.cycle)
        # self.simulator.run_serial(self.settings, self.cycle)

    def calculate_cv(self) -> None:
        self.results = self.analyzer.analyze(self.settings, self.cycle)

    def export(self) -> None:
        self.exporter.export(self.settings, self.cycle)
        dir = self.settings.each_cycle(_cycle=self.cycle)
        logger = generate_logger(f"{self.cycle}", f"{dir}/summary/progress.log")
        logger.info(f"export to cycle{self.cycle + 1:03} is completed")
        close_logger(logger)

    def rmmol(self, last_cycle: bool) -> None:
        rmmol.rmmol(self.settings, self.cycle, last_cycle)

    def clean_cycle(self) -> None:
        rmfile.rmfile(self.settings, self.cycle)

    def is_needed(self) -> bool:
        fn = f"{self.settings.each_cycle(_cycle=self.cycle)}/summary/progress.log"
        if not Path(fn).exists():
            return True

        export_needed: bool = True
        rmmol_needed: bool = self.settings.rmmol
        rmfile_needed: bool = self.settings.rmfile

        with open(fn, "r") as f:
            for line in f:
                if "export to" in line:
                    export_needed = False
                if "reduced" in line:
                    rmmol_needed = False
                if "rmfile" in line:
                    rmfile_needed = False

        return any([export_needed, rmmol_needed, rmfile_needed])

    # def genrepresent(self) -> None:
    #     genrepresent.genrepresent(self.settings)

    def meet_threshold(self) -> bool:
        return self.cycle == self.settings.max_cycle or self.analyzer.is_threshold(
            self.settings, self.results
        )

    def is_pruning(self) -> bool:
        return self.analyzer.is_pruning(self.settings, self.cycle)
